"""
02_react_loop — explicit Reason + Act + Observe cycle.

What's new vs 01_hello_tool:
  1. System prompt instructs the model to reason before every tool call.
  2. A Trace dataclass captures every thought/action/observation.
  3. The loop logs structured steps — you can see exactly why the model
     made each decision, not just what it called.

Mental model:
  ReAct turns the agent's internal monologue into an artifact you can
  inspect, test, and improve. "Why did it call that tool?" becomes
  answerable by reading the trace, not guessing.
"""

from __future__ import annotations

import os
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import anthropic
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# 1. Trace — captures the full reasoning chain for one agent run
#    PRODUCTION VALUE: serialize this to JSON and ship it to your logging
#    system. It's your primary debugging artifact.
# ---------------------------------------------------------------------------

@dataclass
class Step:
    kind: Literal["thought", "action", "observation", "answer"]
    content: str
    tool_name: str | None = None
    tool_input: dict | None = None


@dataclass
class Trace:
    prompt: str
    steps: list[Step] = field(default_factory=list)
    iterations: int = 0

    def add(self, step: Step) -> None:
        self.steps.append(step)

    def thoughts(self) -> list[str]:
        return [s.content for s in self.steps if s.kind == "thought"]

    def actions(self) -> list[Step]:
        return [s for s in self.steps if s.kind == "action"]

    def final_answer(self) -> str | None:
        answers = [s.content for s in self.steps if s.kind == "answer"]
        return answers[-1] if answers else None

    def pretty_print(self) -> None:
        print(f"\n{'='*60}")
        print(f"TRACE — {self.iterations} iteration(s)")
        print(f"PROMPT: {self.prompt}")
        print("="*60)
        for i, step in enumerate(self.steps, 1):
            if step.kind == "thought":
                print(f"\n[{i}] THOUGHT:\n  {step.content}")
            elif step.kind == "action":
                args = json.dumps(step.tool_input, indent=2)
                print(f"\n[{i}] ACTION: {step.tool_name}\n  input: {args}")
            elif step.kind == "observation":
                preview = step.content[:300] + "..." if len(step.content) > 300 else step.content
                print(f"\n[{i}] OBSERVATION:\n  {preview}")
            elif step.kind == "answer":
                print(f"\n[{i}] ANSWER:\n  {step.content}")
        print("="*60)

    def to_dict(self) -> dict:
        """Serialize for logging/storage."""
        return {
            "prompt": self.prompt,
            "iterations": self.iterations,
            "steps": [
                {
                    "kind": s.kind,
                    "content": s.content,
                    "tool_name": s.tool_name,
                    "tool_input": s.tool_input,
                }
                for s in self.steps
            ],
        }


# ---------------------------------------------------------------------------
# 2. Tools — same implementations as 01, kept here for self-containment.
#    In a real project these live in tools/ (see the CLAUDE.md note).
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "get_git_log",
        "description": (
            "Returns the last N git commits for a repo path. "
            "Use to understand recent change velocity and who's been committing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Path to git repo root."},
                "num_commits": {"type": "integer", "default": 5},
            },
            "required": ["repo_path"],
        },
    },
    {
        "name": "check_disk_usage",
        "description": "Returns disk usage for a path in human-readable format.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to inspect."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_directory",
        "description": (
            "Lists files and directories at a path. "
            "Always call this first to understand project structure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to list."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "run_tests",
        "description": (
            "Runs pytest in a directory and returns the summary. "
            "Use to check whether a project's test suite is passing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory to run pytest in."},
                "extra_args": {"type": "string", "default": "--tb=short -q"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_file",
        "description": (
            "Searches for a regex pattern in a file using grep. "
            "Use to locate specific functions, variables, or config keys without reading the whole file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to search."},
                "pattern": {"type": "string", "description": "Regex pattern to search for."},
            },
            "required": ["path", "pattern"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Reads a text file and returns its contents. "
            "Use to inspect source code, configs, or logs before drawing conclusions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative file path."},
                "max_lines": {
                    "type": "integer",
                    "description": "Max lines to return. Defaults to 100.",
                    "default": 100,
                },
            },
            "required": ["path"],
        },
    },
]


def get_git_log(repo_path: str, num_commits: int = 5) -> str:
    path = Path(repo_path).expanduser().resolve()
    if not (path / ".git").exists():
        return f"Error: {path} is not a git repository."
    result = subprocess.run(
        ["git", "log", f"--max-count={num_commits}", "--oneline", "--decorate"],
        cwd=path, capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip() or "No commits found."


def check_disk_usage(path: str) -> str:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return f"Error: path does not exist: {resolved}"
    if shutil.which("du"):
        result = subprocess.run(
            ["du", "-sh", str(resolved)], capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else result.stderr
    return "du not available on this platform."


def list_directory(path: str) -> str:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return f"Error: path does not exist: {resolved}"
    if not resolved.is_dir():
        return f"Error: not a directory: {resolved}"
    entries = sorted(resolved.iterdir(), key=lambda p: (p.is_file(), p.name))
    lines = [f"  {e.name}{'/' if e.is_dir() else ''}" for e in entries[:50]]
    return "\n".join(lines) or "(empty directory)"


def run_tests(path: str, extra_args: str = "--tb=short -q") -> str:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return f"Error: path does not exist: {resolved}"
    if not shutil.which("pytest"):
        return "Error: pytest not found on PATH."
    result = subprocess.run(
        ["pytest"] + extra_args.split() + ["--no-header"],
        cwd=resolved, capture_output=True, text=True, timeout=60,
    )
    output = (result.stdout + result.stderr).strip()
    return ("...(truncated)...\n" + output[-3000:]) if len(output) > 3000 else output


def search_file(path: str, pattern: str) -> str:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return f"Error: file not found: {resolved}"
    if not resolved.is_file():
        return f"Error: not a file: {resolved}"
    if not shutil.which("grep"):
        return "Error: grep not found on PATH."
    result = subprocess.run(
        ["grep", "-n", "--color=never", "-E", pattern, str(resolved)],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode == 1:
        return f"No matches for pattern '{pattern}' in {resolved}"
    if result.returncode != 0:
        return f"grep error: {result.stderr.strip()}"
    lines = result.stdout.strip().splitlines()
    if len(lines) > 200:
        return "\n".join(lines[:200]) + f"\n...(truncated, {len(lines)} total matches)"
    return result.stdout.strip()


def read_file(path: str, max_lines: int = 100) -> str:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return f"Error: file not found: {resolved}"
    if not resolved.is_file():
        return f"Error: not a file: {resolved}"
    try:
        lines = resolved.read_text(errors="replace").splitlines()
        truncated = len(lines) > max_lines
        result = "\n".join(lines[:max_lines])
        if truncated:
            result += f"\n...(truncated at {max_lines} lines, file has {len(lines)} total)"
        return result
    except Exception as e:
        return f"Error reading file: {e}"


TOOL_REGISTRY = {
    "get_git_log": get_git_log,
    "check_disk_usage": check_disk_usage,
    "list_directory": list_directory,
    "run_tests": run_tests,
    "search_file": search_file,
    "read_file": read_file,
}


def execute_tool(tool_name: str, tool_input: dict) -> str:
    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None:
        return f"Error: unknown tool '{tool_name}'"
    try:
        return fn(**tool_input)
    except Exception as e:
        return f"Tool execution error: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# 3. System prompt — the key change from 01_hello_tool.
#
#    We explicitly ask the model to emit its reasoning as text BEFORE each
#    tool call. Claude will produce a text block (the "thought") followed
#    by a tool_use block (the "action"). We capture both.
#
#    ANTI-PATTERN: asking for "Thought: ..." as a prefix inside the tool
#    call itself. Keep reasoning in text blocks, actions in tool_use blocks.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a DevOps assistant with tools for inspecting repos and filesystems.

Before every tool call, briefly explain your reasoning in plain text:
- What you're about to check and why
- What you expect to find
- How it connects to the overall task

After each observation, reason about what it tells you before deciding the next step.

When you have enough information, give a concise, actionable final answer.
Do not call more tools than necessary — stop when you can answer confidently.

Tool guidance:
- Always call list_directory first on an unknown path.
- Call run_tests only if asked about test status or if you see a tests/ directory.
- Call search_file to locate a specific symbol or key before reading the whole file.
- Call read_file when a config or source file is relevant to the question.
- Return tool errors as part of your reasoning — don't silently ignore them."""


# ---------------------------------------------------------------------------
# 4. ReAct loop — same structure as 01, with trace capture added
# ---------------------------------------------------------------------------

def run_agent(user_prompt: str, verbose: bool = True) -> Trace:
    """
    Run the ReAct loop and return a fully populated Trace.

    Returns Trace (not just a string) so callers can inspect the
    reasoning chain, not just the final answer.
    """
    client = anthropic.AnthropicBedrock(aws_region=os.environ.get("AWS_REGION", "us-west-2"))
    model = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    trace = Trace(prompt=user_prompt)
    messages = [{"role": "user", "content": user_prompt}]
    max_iterations = 10

    while trace.iterations < max_iterations:
        trace.iterations += 1

        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Capture the full response for message history
        messages.append({"role": "assistant", "content": response.content})

        # Parse content blocks — text = thought, tool_use = action
        tool_results = []

        for block in response.content:
            if block.type == "text" and block.text.strip():
                # This is the model's reasoning — capture it as a Thought
                trace.add(Step(kind="thought", content=block.text.strip()))
                if verbose:
                    print(f"\nTHOUGHT: {block.text.strip()}")

            elif block.type == "tool_use":
                # Action step
                trace.add(Step(
                    kind="action",
                    content=f"{block.name}({json.dumps(block.input)})",
                    tool_name=block.name,
                    tool_input=block.input,
                ))
                if verbose:
                    print(f"\nACTION: {block.name}({json.dumps(block.input, indent=2)})")

                # Execute and capture observation
                result = execute_tool(block.name, block.input)
                trace.add(Step(kind="observation", content=result))
                if verbose:
                    preview = result[:400] + "..." if len(result) > 400 else result
                    print(f"\nOBSERVATION:\n{preview}")

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        # If no tool calls, the model is done
        if response.stop_reason == "end_turn":
            # The final text block is the answer
            for block in response.content:
                if block.type == "text" and block.text.strip():
                    trace.add(Step(kind="answer", content=block.text.strip()))
            break

        # Feed observations back for next iteration
        if tool_results:
            messages.append({"role": "user", "content": tool_results})

    if trace.iterations >= max_iterations:
        trace.add(Step(
            kind="answer",
            content="Error: max iterations reached without a final answer.",
        ))

    return trace


# ---------------------------------------------------------------------------
# 5. Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "."
    prompt = (
        f"Investigate the project at {target}. "
        "Check its structure, recent commits, test status, and give me a health summary."
    )

    print(f"Prompt: {prompt}")
    trace = run_agent(prompt, verbose=True)

    print("\n" + "="*60)
    print("FINAL ANSWER:")
    print(trace.final_answer() or "(no answer captured)")
    print(f"\nCompleted in {trace.iterations} iteration(s), {len(trace.actions())} tool call(s)")

    # Optionally save trace for later inspection
    import json as _json
    trace_path = Path("trace.json")
    trace_path.write_text(_json.dumps(trace.to_dict(), indent=2))
    print(f"Trace saved to: {trace_path}")