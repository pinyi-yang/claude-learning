"""
Tests for 03_cicd_monitor.

Testing strategy:
  - Unit test local tools (format_ci_report) — deterministic, no API
  - Unit test config builders — verify shape and required fields
  - Integration test each phase with mocked Anthropic client
  - Test phase handoff: investigation JSON correctly feeds act phase
  - Test tool budget enforcement (code-side, not prompt-side)
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from tools.local import format_ci_report, execute_local_tool
from config import (
    GITLAB_INVESTIGATE_TOOLS,
    GITHUB_ACT_TOOLS,
)
from agent import Trace, Step, run_phase


# ---------------------------------------------------------------------------
# Local tool tests
# ---------------------------------------------------------------------------

SAMPLE_REPORT = {
    "pipeline_id": "12345",
    "status": "failed",
    "failed_jobs": [
        {
            "job_name": "pytest",
            "failure_type": "test_failure",
            "root_cause": "AssertionError in test_payment.py::test_refund",
            "relevant_log_lines": ["FAILED test_payment.py::test_refund - AssertionError"],
            "confidence": "high",
        }
    ],
    "summary": "Unit test failure in payment service refund logic.",
    "recommendation": "Fix the refund calculation in payment_service.py line 142.",
}


class TestFormatCiReport:
    def test_formats_basic_report(self):
        result = format_ci_report(json.dumps(SAMPLE_REPORT))
        assert "Pipeline #12345" in result
        assert "pytest" in result
        assert "test_failure" in result
        assert "Fix the refund" in result
        assert "CI triage agent" in result

    def test_includes_log_lines_when_requested(self):
        result = format_ci_report(json.dumps(SAMPLE_REPORT), include_log_lines=True)
        assert "AssertionError" in result
        assert "<details>" in result

    def test_excludes_log_lines_by_default(self):
        result = format_ci_report(json.dumps(SAMPLE_REPORT))
        assert "<details>" not in result

    def test_invalid_json_returns_error(self):
        result = format_ci_report("not valid json{{{")
        assert "Error" in result

    def test_empty_failed_jobs(self):
        report = {**SAMPLE_REPORT, "failed_jobs": [], "status": "passed"}
        result = format_ci_report(json.dumps(report))
        assert "Failed Jobs" not in result
        assert "✅" in result

    def test_multiple_failed_jobs(self):
        report = {
            **SAMPLE_REPORT,
            "failed_jobs": [
                {**SAMPLE_REPORT["failed_jobs"][0]},
                {
                    "job_name": "lint",
                    "failure_type": "config",
                    "root_cause": "ruff config missing",
                    "relevant_log_lines": [],
                    "confidence": "medium",
                },
            ],
        }
        result = format_ci_report(json.dumps(report))
        assert "pytest" in result
        assert "lint" in result


class TestExecuteLocalTool:
    def test_dispatches_format_ci_report(self):
        result = execute_local_tool("format_ci_report", {"report_json": json.dumps(SAMPLE_REPORT)})
        assert "Pipeline" in result

    def test_unknown_tool_returns_error(self):
        result = execute_local_tool("nonexistent", {})
        assert "Error" in result

    def test_bad_args_returns_error_not_raise(self):
        result = execute_local_tool("format_ci_report", {"wrong_arg": "value"})
        assert "Error" in result


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------

class TestConfig:
    def test_gitlab_investigate_tools_are_read_only(self):
        """Ensure no write tools sneak into the investigation allowlist."""
        write_indicators = ["create", "update", "delete", "post", "merge", "approve"]
        for tool in GITLAB_INVESTIGATE_TOOLS:
            for indicator in write_indicators:
                assert indicator not in tool.lower(), (
                    f"Write tool '{tool}' found in GITLAB_INVESTIGATE_TOOLS — "
                    f"investigation phase must be read-only."
                )

    def test_github_act_tools_are_write_only(self):
        """Act phase should only have write tools — no reads needed."""
        read_indicators = ["list_", "get_", "search_"]
        for tool in GITHUB_ACT_TOOLS:
            for indicator in read_indicators:
                assert indicator not in tool.lower(), (
                    f"Read tool '{tool}' found in GITHUB_ACT_TOOLS — "
                    f"act phase should be write-only."
                )

    def test_gitlab_server_requires_token(self, monkeypatch):
        from config import gitlab_mcp_server
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        with pytest.raises(ValueError, match="GITLAB_TOKEN"):
            gitlab_mcp_server(GITLAB_INVESTIGATE_TOOLS)

    def test_github_server_requires_token(self, monkeypatch):
        from config import github_mcp_server
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with pytest.raises(ValueError, match="GITHUB_TOKEN"):
            github_mcp_server(GITHUB_ACT_TOOLS)

    def test_gitlab_server_shape(self, monkeypatch):
        from config import gitlab_mcp_server
        monkeypatch.setenv("GITLAB_TOKEN", "test-token")
        server = gitlab_mcp_server(["get_pipeline"])
        assert server["type"] == "url"
        assert "gitlab" in server["url"]
        assert server["allowed_tools"] == ["get_pipeline"]
        assert "authorization_token" in server


# ---------------------------------------------------------------------------
# Phase loop integration tests — mocked Anthropic client
# ---------------------------------------------------------------------------

class TestRunPhase:
    def _make_response(self, blocks, stop_reason="end_turn"):
        r = MagicMock()
        r.content = blocks
        r.stop_reason = stop_reason
        return r

    def _text_block(self, text):
        b = MagicMock()
        b.type = "text"
        b.text = text
        return b

    def _tool_block(self, name, input_, id_="tu_1"):
        b = MagicMock()
        b.type = "tool_use"
        b.name = name
        b.input = input_
        b.id = id_
        return b

    def _make_trace(self):
        return Trace(project_id="test/proj", pipeline_id="999", github_pr="test/proj#1")

    def test_single_turn_no_tools(self):
        with patch("agent.anthropic.Anthropic") as mock_cls:
            client = MagicMock()
            mock_cls.return_value = client
            client.messages.create.return_value = self._make_response([
                self._text_block("Investigation complete. No failures found."),
            ])

            trace = self._make_trace()
            result = run_phase(
                client=client,
                system="Test system",
                messages=[{"role": "user", "content": "Check pipeline"}],
                mcp_servers=[],
                phase="investigate",
                trace=trace,
            )

        assert "No failures" in result
        assert len([s for s in trace.steps if s.kind == "answer"]) == 1

    def test_local_tool_executed_by_agent(self):
        """Local tools (format_ci_report) must be executed by us, not Anthropic."""
        with patch("agent.anthropic.Anthropic") as mock_cls:
            client = MagicMock()
            mock_cls.return_value = client
            client.messages.create.side_effect = [
                self._make_response([
                    self._tool_block("format_ci_report", {"report_json": json.dumps(SAMPLE_REPORT)}, "tu_local"),
                ], stop_reason="tool_use"),
                self._make_response([
                    self._text_block("Comment formatted and ready."),
                ]),
            ]

            trace = self._make_trace()
            result = run_phase(
                client=client,
                system="Test",
                messages=[{"role": "user", "content": "Format the report"}],
                mcp_servers=[],
                phase="act",
                trace=trace,
            )

        # Local tool result should appear in second API call's messages
        second_call_args = client.messages.create.call_args_list[1]
        messages_sent = second_call_args[1]["messages"]
        # Last message should be user turn with tool_result
        last_msg = messages_sent[-1]
        assert last_msg["role"] == "user"
        assert any(
            item.get("type") == "tool_result"
            for item in last_msg["content"]
        )

    def test_tool_budget_enforced(self):
        """After max_tool_calls, agent should stop calling tools."""
        with patch("agent.anthropic.Anthropic") as mock_cls:
            client = MagicMock()
            mock_cls.return_value = client
            # Always return a tool call
            client.messages.create.return_value = self._make_response([
                self._tool_block("list_project_pipelines", {"project_id": "test"})
            ], stop_reason="tool_use")

            trace = self._make_trace()
            run_phase(
                client=client,
                system="Test",
                messages=[{"role": "user", "content": "Go"}],
                mcp_servers=[],
                phase="investigate",
                trace=trace,
                max_iterations=10,
                max_tool_calls=3,  # hard cap
            )

        # Actions in trace should not exceed max_tool_calls
        actions = [s for s in trace.steps if s.kind == "action"]
        assert len(actions) <= 3

    def test_thoughts_captured_per_phase(self):
        with patch("agent.anthropic.Anthropic") as mock_cls:
            client = MagicMock()
            mock_cls.return_value = client
            client.messages.create.return_value = self._make_response([
                self._text_block("I will check the pipeline status first."),
            ])

            trace = self._make_trace()
            run_phase(
                client=client,
                system="Test",
                messages=[{"role": "user", "content": "Check"}],
                mcp_servers=[],
                phase="investigate",
                trace=trace,
            )

        thoughts = [s for s in trace.steps if s.kind == "thought" and s.phase == "investigate"]
        assert len(thoughts) >= 1
        assert "pipeline" in thoughts[0].content.lower()