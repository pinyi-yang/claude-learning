# 01_hello_tool

Minimal working agent with tool use. No framework — just the Anthropic SDK and a while loop.

## What you'll learn

- How to define tools as JSON schema
- How the model returns `tool_use` blocks
- How to implement the executor (your code runs the tools)
- How to feed `tool_result` back into the message history
- How to guard against infinite loops

## Setup

```bash
# Install uv if you haven't
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync --extra dev

# Set your API key
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
```

## Run it

```bash
# Inspect the current directory
uv run python agent.py .

# Inspect a specific repo
uv run python agent.py ~/my-project
```

## Run tests

```bash
uv run pytest tests/ -v
```

## Key files

```
agent.py          — the agent: tool definitions, implementations, loop
tests/
  test_agent.py   — unit tests for tools + mocked loop integration test
pyproject.toml    — deps and tooling config
```

## What to try next

1. Add a `run_tests` tool that runs `pytest` in a given directory and returns
   the summary output. Ask the agent: "Are my tests passing?"

2. Add a `check_open_ports` tool using `psutil` or `ss`. Ask: "What's
   listening on this machine?"

3. Extend the system prompt to handle tool errors explicitly — tell the model
   what to do when a tool returns an error string.

4. Add token usage logging: `response.usage.input_tokens` and
   `response.usage.output_tokens`. Track cumulative cost across the loop.

5. Try asking the agent something it CAN'T answer with the current tools.
   Observe how it responds. Then add the tool it needs.

## Anti-patterns to watch for

- **Appending only text to messages**: you must append the full `response.content`
  list (including `tool_use` blocks) or the API rejects the history.
- **No max_iterations guard**: a confused model can loop indefinitely.
- **Passing raw model output to subprocess**: always validate paths and inputs.
- **Raising exceptions in tool executors**: return error strings instead — the
  model can recover; a crash cannot.
