"""
Tests for 01_hello_tool.

Testing strategy for agents:
  - Unit test tools in isolation (no API calls)
  - Integration test the loop with a mocked client
  - Never hit the real API in tests — it's slow and costs money

Run with: pytest tests/ -v
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Import the tool functions directly — test them independently of the agent loop
from agent import (
    execute_tool,
    get_git_log,
    check_disk_usage,
    list_directory,
    run_agent,
)


# ---------------------------------------------------------------------------
# Tool unit tests — fast, no API, no subprocess where possible
# ---------------------------------------------------------------------------

class TestListDirectory:
    def test_lists_real_directory(self, tmp_path):
        (tmp_path / "file_a.txt").write_text("hello")
        (tmp_path / "subdir").mkdir()

        result = list_directory(str(tmp_path))
        assert "subdir/" in result
        assert "file_a.txt" in result

    def test_nonexistent_path_returns_error(self):
        result = list_directory("/nonexistent/path/xyz")
        assert "Error" in result

    def test_file_path_returns_error(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("content")
        result = list_directory(str(f))
        assert "Error" in result

    def test_empty_directory(self, tmp_path):
        result = list_directory(str(tmp_path))
        assert "(empty directory)" in result


class TestCheckDiskUsage:
    def test_existing_path_returns_something(self, tmp_path):
        result = check_disk_usage(str(tmp_path))
        # Should not be an error on any platform
        assert "Error" not in result or "not available" in result

    def test_nonexistent_path_returns_error(self):
        result = check_disk_usage("/nonexistent/xyz")
        assert "Error" in result


class TestGetGitLog:
    def test_non_repo_returns_error(self, tmp_path):
        result = get_git_log(str(tmp_path))
        assert "Error" in result

    def test_git_repo_returns_commits(self, tmp_path):
        """Create a minimal git repo and verify log works."""
        import subprocess
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        (tmp_path / "README.md").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial commit"], cwd=tmp_path, capture_output=True)

        result = get_git_log(str(tmp_path), num_commits=3)
        assert "initial commit" in result


class TestExecuteTool:
    def test_unknown_tool_returns_error(self):
        result = execute_tool("nonexistent_tool", {})
        assert "Error" in result
        assert "unknown tool" in result

    def test_dispatches_to_list_directory(self, tmp_path):
        result = execute_tool("list_directory", {"path": str(tmp_path)})
        assert "Error" not in result or "empty" in result

    def test_handles_tool_exception_gracefully(self, tmp_path):
        # Pass wrong argument type — should return error string, not raise
        result = execute_tool("list_directory", {"path": None})
        assert "Error" in result


# ---------------------------------------------------------------------------
# Agent loop integration test — mock the Anthropic client
# ---------------------------------------------------------------------------

class TestAgentLoop:
    def _make_tool_use_response(self, tool_name: str, tool_input: dict, tool_id: str = "tu_123"):
        """Helper: build a mock response that requests a tool call."""
        block = MagicMock()
        block.type = "tool_use"
        block.name = tool_name
        block.input = tool_input
        block.id = tool_id

        response = MagicMock()
        response.stop_reason = "tool_use"
        response.content = [block]
        return response

    def _make_end_turn_response(self, text: str):
        """Helper: build a mock response that ends the loop."""
        block = MagicMock()
        block.type = "text"
        block.text = text
        # text blocks don't have a .type == "tool_use" check
        del block.type  # can't del MagicMock attrs, so:
        block.type = "text"

        response = MagicMock()
        response.stop_reason = "end_turn"
        response.content = [block]
        return response

    def test_single_turn_no_tools(self, tmp_path):
        """Agent should return immediately when model uses no tools."""
        with patch("agent.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client

            mock_client.messages.create.return_value = self._make_end_turn_response(
                "All good!"
            )

            result = run_agent("Is everything ok?", verbose=False)
            assert result == "All good!"
            assert mock_client.messages.create.call_count == 1

    def test_tool_call_then_end(self, tmp_path):
        """Agent should call one tool then finish."""
        with patch("agent.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client

            mock_client.messages.create.side_effect = [
                self._make_tool_use_response(
                    "list_directory", {"path": str(tmp_path)}
                ),
                self._make_end_turn_response("Directory looks empty."),
            ]

            result = run_agent(f"Check {tmp_path}", verbose=False)
            assert result == "Directory looks empty."
            assert mock_client.messages.create.call_count == 2

    def test_max_iterations_guard(self):
        """Agent must not loop forever — max_iterations should kick in."""
        with patch("agent.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client

            # Always return a tool_use — never end_turn
            mock_client.messages.create.return_value = self._make_tool_use_response(
                "list_directory", {"path": "/tmp"}
            )

            result = run_agent("Loop forever", verbose=False)
            assert "max iterations" in result
            # Should have stopped at 10
            assert mock_client.messages.create.call_count == 10
