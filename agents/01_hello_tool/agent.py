"""
01_hello_tool — minimal working tool-use agent.

Mental model:
  - Tool definitions are just JSON schema describing what the model CAN call.
  - The model returns a `tool_use` block when it wants to call something.
  - YOUR code actually executes the function and returns a `tool_result`.
  - The loop continues until stop_reason == "end_turn" (no more tool calls).

You are the executor. The model is the decision-maker.
"""

import os
import json
import shutil
import subprocess
from pathlib import Path

import anthropic

# ---------------------------------------------------------------------------
# 1. Tool definitions — describe capabilities to the model
#    ANTI-PATTERN: vague descriptions. The model uses these to decide WHEN
#    to call a tool. Be specific about what each tool returns and when to use it.
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "get_git_log",
        "description": (
            "Returns the last N git commits for a repository path. "
            "Use this to understand recent activity and change velocity."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute or relative path to the git repository root.",
                },
                "num_commits": {
                    "type": "integer",
                    "description": "Number of recent commits to return. Default 5.",
                    "default": 5,
                },
            },
            "required": ["repo_path"],
        },
    },
    {
        "name": "check_disk_usage",
        "description": (
            "Returns disk usage for a given directory path in human-readable format. "
            "Use this when assessing storage health or finding large directories."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path to check disk usage for.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_directory",
        "description": (
            "Lists files and directories at a given path. "
            "Use this to understand project structure before diving deeper."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path to list.",
                },
            },
            "required": ["path"],
        },
    },
]


# ---------------------------------------------------------------------------
# 2. Tool implementations — the actual Python functions
#    PRODUCTION PITFALL: always validate/sanitize inputs before running
#    shell commands. Never pass raw model output directly to subprocess.
# ---------------------------------------------------------------------------

def get_git_log(repo_path: str, num_commits: int = 5) -> str:
    """Return recent git log for a repo."""
    path = Path(repo_path).expanduser().resolve()
    if not (path / ".git").exists():
        return f"Error: {path} is not a git repository."

    result = subprocess.run(
        ["git", "log", f"--max-count={num_commits}", "--oneline", "--decorate"],
        cwd=path,
        capture_output=True,
        text=True,
        timeout=10,  # always set timeouts on subprocess calls
    )
    if result.returncode != 0:
        return f"Git error: {result.stderr}"
    return result.stdout.strip() or "No commits found."


def check_disk_usage(path: str) -> str:
    """Return disk usage for a path."""
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return f"Error: path does not exist: {resolved}"

    # Use 'du' on Unix; fallback message on Windows
    if shutil.which("du"):
        result = subprocess.run(
            ["du", "-sh", str(resolved)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else result.stderr
    return "du not available on this platform."


def list_directory(path: str) -> str:
    """List directory contents."""
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return f"Error: path does not exist: {resolved}"
    if not resolved.is_dir():
        return f"Error: not a directory: {resolved}"

    entries = sorted(resolved.iterdir(), key=lambda p: (p.is_file(), p.name))
    lines = []
    for entry in entries[:50]:  # cap output — long lists waste context window
        indicator = "/" if entry.is_dir() else ""
        lines.append(f"  {entry.name}{indicator}")
    if len(list(resolved.iterdir())) > 50:
        lines.append("  ... (truncated)")
    return "\n".join(lines) or "(empty directory)"


# ---------------------------------------------------------------------------
# 3. Tool router — maps tool names to their implementations
#    ANTI-PATTERN: using eval() or getattr() to dispatch. Keep an explicit map.
# ---------------------------------------------------------------------------

TOOL_REGISTRY = {
    "get_git_log": get_git_log,
    "check_disk_usage": check_disk_usage,
    "list_directory": list_directory,
}


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a tool by name and return its string result."""
    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None:
        # Return an error string — never raise here. The model can recover
        # from a tool error if you return it as a result, but an exception
        # will crash your loop entirely.
        return f"Error: unknown tool '{tool_name}'"
    try:
        return fn(**tool_input)
    except Exception as e:
        return f"Tool execution error: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# 4. The agentic loop — the core of every agent
#    This is intentionally minimal. In production you'd add:
#      - max_iterations guard (prevent infinite loops)
#      - token usage tracking
#      - structured logging per turn
#      - timeout handling
# ---------------------------------------------------------------------------

def run_agent(user_prompt: str, verbose: bool = True) -> str:
    """
    Run the agent loop until the model stops requesting tools.

    Returns the final text response.
    """
    client = anthropic.AnthropicBedrock(aws_region=os.environ.get("AWS_REGION", "us-west-2"))
    model = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "us.anthropic.claude-sonnet-4-5-v1:0")

    messages = [{"role": "user", "content": user_prompt}]

    system = """You are a DevOps assistant with access to tools for inspecting
local repositories and filesystems. When asked about a repo or directory:
1. First list the directory to understand structure.
2. Check git log if it's a repo.
3. Check disk usage if relevant.
4. Synthesize your findings into a clear, actionable summary.

Always use tools before answering — don't guess at filesystem state."""

    iteration = 0
    max_iterations = 10  # PRODUCTION PITFALL: always set a hard cap

    while iteration < max_iterations:
        iteration += 1
        if verbose:
            print(f"\n--- Turn {iteration} ---")

        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=system,
            tools=TOOLS,
            messages=messages,
        )

        if verbose:
            print(f"Stop reason: {response.stop_reason}")

        # Append the assistant's full response to message history
        # ANTI-PATTERN: only appending the text. You must include ALL content
        # blocks (including tool_use blocks) or the API will reject the history.
        messages.append({"role": "assistant", "content": response.content})

        # If the model is done — no more tool calls
        if response.stop_reason == "end_turn":
            # Extract the final text response
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text
            return "(no text response)"

        # Process tool calls
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            if verbose:
                print(f"  Calling tool: {block.name}({json.dumps(block.input)})")

            result = execute_tool(block.name, block.input)

            if verbose:
                # Truncate for readability in the terminal
                preview = result[:200] + "..." if len(result) > 200 else result
                print(f"  Result: {preview}")

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })

        # Feed results back to the model
        messages.append({"role": "user", "content": tool_results})

    return "Error: max iterations reached — agent did not complete."


# ---------------------------------------------------------------------------
# 5. Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    # Default to current directory; accept a path argument
    target = sys.argv[1] if len(sys.argv) > 1 else "."

    prompt = f"Give me a health summary of the repository or directory at: {target}"
    print(f"Prompt: {prompt}\n")

    result = run_agent(prompt, verbose=True)
    print("\n=== Final Answer ===")
    print(result)
