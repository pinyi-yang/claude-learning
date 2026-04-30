"""
Tests for 02_react_loop.

New things to test vs 01_hello_tool:
  - Trace captures thoughts, actions, observations correctly
  - Thoughts are extracted from text blocks before tool_use blocks
  - Final answer lands in trace.final_answer()
  - to_dict() round-trips cleanly (important for logging pipelines)
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from agent import (
    Trace, Step,
    execute_tool, read_file, run_tests,
    run_agent,
)


# ---------------------------------------------------------------------------
# Trace unit tests — no API, no filesystem
# ---------------------------------------------------------------------------

class TestTrace:
    def test_empty_trace(self):
        t = Trace(prompt="hello")
        assert t.thoughts() == []
        assert t.actions() == []
        assert t.final_answer() is None

    def test_add_steps(self):
        t = Trace(prompt="hello")
        t.add(Step(kind="thought", content="I should check the directory first."))
        t.add(Step(kind="action", content="list_directory(.)", tool_name="list_directory", tool_input={"path": "."}))
        t.add(Step(kind="observation", content="agent.py\ntests/"))
        t.add(Step(kind="answer", content="Looks good."))

        assert len(t.thoughts()) == 1
        assert len(t.actions()) == 1
        assert t.final_answer() == "Looks good."

    def test_to_dict_round_trips(self):
        t = Trace(prompt="test", iterations=2)
        t.add(Step(kind="thought", content="Reasoning..."))
        t.add(Step(kind="action", content="list_directory(.)", tool_name="list_directory", tool_input={"path": "."}))

        d = t.to_dict()
        serialized = json.dumps(d)  # must not raise
        parsed = json.loads(serialized)

        assert parsed["prompt"] == "test"
        assert parsed["iterations"] == 2
        assert len(parsed["steps"]) == 2
        assert parsed["steps"][0]["kind"] == "thought"

    def test_multiple_answers_returns_last(self):
        t = Trace(prompt="q")
        t.add(Step(kind="answer", content="First answer."))
        t.add(Step(kind="answer", content="Revised answer."))
        assert t.final_answer() == "Revised answer."


# ---------------------------------------------------------------------------
# New tool tests
# ---------------------------------------------------------------------------

class TestReadFile:
    def test_reads_existing_file(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("line1\nline2\nline3")
        result = read_file(str(f))
        assert "line1" in result
        assert "line3" in result

    def test_truncates_at_max_lines(self, tmp_path):
        f = tmp_path / "big.txt"
        f.write_text("\n".join(f"line {i}" for i in range(200)))
        result = read_file(str(f), max_lines=10)
        assert "truncated" in result
        assert "line 9" in result
        assert "line 100" not in result

    def test_nonexistent_file_returns_error(self):
        result = read_file("/nonexistent/file.txt")
        assert "Error" in result

    def test_directory_returns_error(self, tmp_path):
        result = read_file(str(tmp_path))
        assert "Error" in result


class TestRunTests:
    def test_nonexistent_path_returns_error(self):
        result = run_tests("/nonexistent/path")
        assert "Error" in result


# ---------------------------------------------------------------------------
# ReAct loop integration tests — mocked API
# ---------------------------------------------------------------------------

class TestReActLoop:
    def _text_block(self, text: str):
        block = MagicMock()
        block.type = "text"
        block.text = text
        return block

    def _tool_use_block(self, name: str, input_: dict, id_: str = "tu_1"):
        block = MagicMock()
        block.type = "tool_use"
        block.name = name
        block.input = input_
        block.id = id_
        return block

    def _response(self, blocks, stop_reason="tool_use"):
        r = MagicMock()
        r.content = blocks
        r.stop_reason = stop_reason
        return r

    def test_thought_captured_from_text_block(self, tmp_path):
        with patch("agent.anthropic.Anthropic") as mock_cls:
            client = MagicMock()
            mock_cls.return_value = client

            # Turn 1: thought + tool call
            # Turn 2: thought + end_turn
            client.messages.create.side_effect = [
                self._response([
                    self._text_block("I should list the directory first."),
                    self._tool_use_block("list_directory", {"path": str(tmp_path)}),
                ], stop_reason="tool_use"),
                self._response([
                    self._text_block("The directory is empty. All good."),
                ], stop_reason="end_turn"),
            ]

            trace = run_agent(f"Check {tmp_path}", verbose=False)

        assert len(trace.thoughts()) >= 1
        assert "list the directory" in trace.thoughts()[0]
        assert len(trace.actions()) == 1
        assert trace.actions()[0].tool_name == "list_directory"
        assert trace.final_answer() is not None

    def test_observation_captured_after_action(self, tmp_path):
        (tmp_path / "README.md").write_text("hello")

        with patch("agent.anthropic.Anthropic") as mock_cls:
            client = MagicMock()
            mock_cls.return_value = client

            client.messages.create.side_effect = [
                self._response([
                    self._tool_use_block("list_directory", {"path": str(tmp_path)}),
                ], stop_reason="tool_use"),
                self._response([
                    self._text_block("Done."),
                ], stop_reason="end_turn"),
            ]

            trace = run_agent("Check it", verbose=False)

        observations = [s for s in trace.steps if s.kind == "observation"]
        assert len(observations) == 1
        assert "README.md" in observations[0].content

    def test_max_iterations_populates_error_answer(self):
        with patch("agent.anthropic.Anthropic") as mock_cls:
            client = MagicMock()
            mock_cls.return_value = client

            # Always returns a tool call — never ends
            client.messages.create.return_value = self._response([
                self._tool_use_block("list_directory", {"path": "/tmp"}),
            ], stop_reason="tool_use")

            trace = run_agent("Loop forever", verbose=False)

        assert trace.iterations == 10
        assert "max iterations" in trace.final_answer()

    def test_trace_serializable_after_run(self, tmp_path):
        with patch("agent.anthropic.Anthropic") as mock_cls:
            client = MagicMock()
            mock_cls.return_value = client

            client.messages.create.return_value = self._response([
                self._text_block("Nothing to do."),
            ], stop_reason="end_turn")

            trace = run_agent("Quick check", verbose=False)

        # Must serialize without error — critical for logging pipelines
        serialized = json.dumps(trace.to_dict())
        assert len(serialized) > 0