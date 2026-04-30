# 02_react_loop

Explicit Reason + Act + Observe cycle with a full trace captured per run.

## What's new vs 01_hello_tool

| | 01_hello_tool | 02_react_loop |
|---|---|---|
| Reasoning | Implicit (inside model weights) | Explicit (captured as `Thought` steps) |
| Return value | `str` (final answer only) | `Trace` (full reasoning chain) |
| Debuggability | "What did it call?" | "Why did it call that?" |
| Persistence | Nothing saved | `trace.json` written per run |
| Tools | 3 | 5 (+ `read_file`, `run_tests`) |

## Setup

```bash
uv sync --extra dev
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
```

## Run it

```bash
# Investigate a directory
uv run python agent.py .

# Investigate a specific repo
uv run python agent.py ~/my-project
```

## Run tests

```bash
uv run pytest tests/ -v
```

## Reading a trace

After a run, `trace.json` contains the full reasoning chain:

```json
{
  "prompt": "Investigate the project at .",
  "iterations": 3,
  "steps": [
    {"kind": "thought", "content": "I'll start by listing the directory..."},
    {"kind": "action",  "tool_name": "list_directory", "tool_input": {"path": "."}},
    {"kind": "observation", "content": "agent.py\ntests/\npyproject.toml"},
    {"kind": "thought", "content": "There's a tests/ directory, I should run them..."},
    {"kind": "action",  "tool_name": "run_tests", "tool_input": {"path": "."}},
    {"kind": "observation", "content": "3 passed in 0.42s"},
    {"kind": "answer",  "content": "The project looks healthy. Tests pass."}
  ]
}
```

This is the artifact you'd ship to your logging/observability system in production.

## What to try next

1. Ask the agent to investigate a repo where tests are failing. Read the
   trace — does the reasoning chain correctly identify why?

2. Add a `search_file(path, pattern)` tool using `grep`. Ask:
   "Are there any hardcoded secrets in this repo?"

3. Modify the system prompt to be more conservative — tell the agent to
   call at most 3 tools before answering. Does it respect the constraint?

4. Compare traces across two runs of the same prompt. Are the reasoning
   chains consistent? Inconsistency here is a signal your tool descriptions
   need tightening.

5. Build a `trace_diff(trace_a, trace_b)` utility that highlights where
   two runs diverged. This is the beginning of eval tooling.