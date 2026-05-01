# 03_cicd_monitor

Two-phase CI/CD triage agent using Anthropic MCP proxy.

Investigates GitLab pipeline failures → posts findings to GitHub PR.

## What's new vs 02_react_loop

| | 02_react_loop | 03_cicd_monitor |
|---|---|---|
| Tools | Built-in (local) | MCP (remote) + local |
| Tool execution | Your code | Anthropic API (MCP) + your code (local) |
| Phases | Single | Two: investigate → act |
| Tool visibility | All tools always | Allowlisted per phase |
| Trust boundary | None | Read-only investigate, write-only act |
| Output | Terminal | GitHub PR comment |

## Key concepts

**Tool allowlisting** — each phase passes `allowed_tools` to the MCP server.
The model only sees tools it's allowed to call. Investigation phase cannot
post comments; act phase cannot read GitLab. Enforced by the API, not prompts.

**Local + MCP tools together** — `format_ci_report` is a local tool (you execute it).
GitLab and GitHub tools are MCP (Anthropic executes them). Both appear in the same
loop; you distinguish them by checking if the tool name is in `LOCAL_TOOL_SCHEMAS`.

**Two-phase handoff** — the investigation result is structured JSON that feeds
the act phase prompt. This decouples reading from writing and makes each phase
independently testable.

## Setup

```bash
uv sync --extra dev

# Required tokens
echo "GITLAB_TOKEN=glpat-xxxx"   >> .env   # read_api scope
echo "GITHUB_TOKEN=github_pat_xx" >> .env  # repo scope (for PR comments)
echo "ANTHROPIC_API_KEY=sk-ant-xx" >> .env
```

## Run

```bash
uv run python agent.py <gitlab_project_id> <pipeline_id> <github_repo> <pr_number>

# Example:
uv run python agent.py myorg/backend 98765432 myorg/backend 123
```

## Test

```bash
uv run pytest tests/ -v
```

## File structure

```
agent.py         — two-phase loop, MCP config, trace
config.py        — MCP server builders, tool allowlists
prompts.py       — system prompts (separated for easy iteration)
tools/
  local.py       — format_ci_report (runs in your process)
tests/
  test_agent.py  — unit + integration tests, no real API calls
```

## What to try next

1. **Tighten the allowlist further.** Remove one tool from
   `GITLAB_INVESTIGATE_TOOLS` and observe how the agent adapts.
   Does it find a workaround? Does quality drop?

2. **Add a router call.** Before phase 1, make a cheap `claude-haiku`
   call that reads the pipeline summary and decides which 3 tools are
   most likely needed. Pass only those. Measure token savings.

3. **Add a flakiness detector.** If the same job has failed 3+ times
   in recent pipelines with different error messages, classify it as
   `flaky` rather than a real regression. Add a `list_project_pipelines`
   call to check history.

4. **Write a deterministic eval.** Create a fixture with a known
   GitLab pipeline JSON response and assert that the agent correctly
   classifies the failure type. This is your first eval harness.

5. **Add human-in-the-loop.** Before posting the GitHub comment, print
   the formatted comment and ask for confirmation. This is a preview
   of the pattern you'll use in 07_release_manager.