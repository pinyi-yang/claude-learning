# 03 — CI/CD Triage Agent

Two-phase agent that investigates GitHub Actions CI failures on a PR and posts a triage comment.

## What it demonstrates

1. **MCP servers via Anthropic API** — no manual tool schemas for GitHub tools
2. **Tool allowlisting per phase** — investigation phase is read-only; act phase is write-only
3. **Phase handoff via structured JSON** — investigation output feeds the act prompt
4. **Local tools alongside MCP tools** — `format_ci_report` runs in-process

## Architecture

```
Phase 1 (investigate)              Phase 2 (act)
  MCP: GitHub Actions tools    →     MCP: GitHub write tools
  - actions_list                     - create_pull_request_review
  - actions_get                      - add_pull_request_review_comment
  - get_job_logs                     - create_issue
  Local: none                        Local: format_ci_report
  Output: structured JSON            Output: PR comment posted
```

## Setup

1. Copy `.env.example` to `.env` and fill in:
   - `GITHUB_TOKEN` — GitHub PAT with `repo` scope
   - `AWS_REGION` and Bedrock model ARNs (or `ANTHROPIC_API_KEY` for direct API)

2. Install dependencies from the repo root:
   ```bash
   pip install -r requirements.txt
   ```

## Run

```bash
cd agents/03_ci_cd
python agent.py <owner/repo> <pr_number>

# Example — triage PR #4 in this repo:
python agent.py pinyi-yang/claude-learning 4
```

The agent will:
1. Find the latest failed GitHub Actions run on the PR
2. List failed jobs and fetch their logs
3. Produce a structured JSON triage report
4. Format and post it as a PR comment

Trace is saved to `trace_pr<pr_number>.json`.

## Tests

```bash
PYTHONPATH=agents/03_ci_cd python -m pytest agents/03_ci_cd/tests/ -v
```

Tests use mocked Anthropic clients — no API calls, no tokens needed.

## What to try next

1. Run the agent against a real PR with a failing CI job
2. Add a third MCP tool to Phase 1 (e.g. `list_repos`) and observe how tool allowlisting prevents it from being used in Phase 2
3. Extend `format_ci_report` to include a flakiness score based on job history
4. Add a Phase 3: auto-open a Jira ticket for `high` confidence failures
