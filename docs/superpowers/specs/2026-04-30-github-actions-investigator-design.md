---
title: Replace GitLab Phase 1 with GitHub Actions investigator
date: 2026-04-30
status: approved
---

## Goal

Replace the agent's GitLab investigation phase with a GitHub Actions investigation phase, so the agent can triage a GitHub Actions CI failure on a PR and post findings as a PR comment — all within GitHub.

## Inputs

Before: `(project_id, pipeline_id, github_repo, github_pr_number)`  
After: `(repo, pr_number)` — e.g. `("pinyi-yang/claude-learning", 4)`

The agent discovers the relevant Actions run ID itself during Phase 1.

## Files Changed

| File | Change |
|------|--------|
| `agents/03_ci_cd/config.py` | Remove `gitlab_mcp_server()` and `GITLAB_INVESTIGATE_TOOLS`. Add `GITHUB_INVESTIGATE_TOOLS`. |
| `agents/03_ci_cd/agent.py` | Update `Trace` fields and `run_agent()` signature. Phase 1 uses GitHub MCP instead of GitLab. |
| `agents/03_ci_cd/prompts.py` | Rewrite `INVESTIGATE_SYSTEM` for GitHub Actions. `ACT_SYSTEM` unchanged. |
| `agents/03_ci_cd/tests/test_agent.py` | Remove GitLab config tests. Add GitHub investigate tool test. Update `_make_trace()`. |

**Unchanged:** `tools/local.py`, `format_ci_report`, Phase 2 (`GITHUB_ACT_TOOLS`, `github_mcp_server()`), `run_phase()` loop.

## config.py

Remove:
- `gitlab_mcp_server()`
- `GITLAB_INVESTIGATE_TOOLS`

Add:
```python
GITHUB_INVESTIGATE_TOOLS = [
    "actions_list",   # list workflow runs for the PR; list jobs within a run
    "actions_get",    # get details of a specific run or job
    "get_job_logs",   # fetch raw log content for a failed job
]
```

Both phases now use `github_mcp_server()` with different `allowed_tools`.

## agent.py

**`Trace` dataclass:** Replace `project_id: str` and `pipeline_id: str` with `repo: str` and `pr_number: int`. Update `to_dict()` accordingly.

**`run_agent()` signature:**
```python
def run_agent(repo: str, pr_number: int, verbose: bool = True) -> Trace:
```

**Phase 1:** Pass `github_mcp_server(GITHUB_INVESTIGATE_TOOLS)` instead of `gitlab_mcp_server(GITLAB_INVESTIGATE_TOOLS)`.

**Phase 1 prompt:**
```python
investigate_prompt = (
    f"Investigate the GitHub Actions CI failures on PR #{pr_number} "
    f"in repo '{repo}'. Find the most recent failed workflow run, "
    f"identify which jobs failed and why, and produce the structured JSON report."
)
```

**Entry point:** Update `sys.argv` parsing to `repo` + `pr_number`.

## prompts.py

`INVESTIGATE_SYSTEM` rewritten:

```
You are a CI/CD triage specialist with read access to GitHub Actions.

Your job: given a GitHub repo and PR number, determine exactly what failed and why.

## Investigation strategy
Follow this order:
1. List recent workflow runs for the PR — find the latest failed run
2. List jobs in that run to identify which ones failed
3. For each failed job: fetch its logs and find the root cause
4. Classify: test failure, infra issue, config problem, or flaky

## Log analysis rules
- Logs can be large. Look for ERROR, FAILED, exception tracebacks, exit codes.
- Distinguish: did the job fail because of the code, or the environment?
- Note the exact failing test name or command.

## Reasoning
Think step by step before each tool call. State what you're looking for and why.
After each observation, update your hypothesis before proceeding.

## Output format
When investigation is complete, output a structured JSON block:
```json
{
  "pipeline_id": "<run_id>",
  "status": "failed",
  "failed_jobs": [
    {
      "job_name": "...",
      "failure_type": "test_failure | infra | config | flaky",
      "root_cause": "...",
      "relevant_log_lines": ["..."],
      "confidence": "high | medium | low"
    }
  ],
  "summary": "One sentence plain-English summary.",
  "recommendation": "What the author should do next."
}
```

Do not post any comments or take any write actions. Investigation only.
```

`ACT_SYSTEM` unchanged.

## tests/test_agent.py

**Remove:**
- `TestConfig::test_gitlab_server_requires_token`
- `TestConfig::test_gitlab_server_shape`
- Import of `gitlab_mcp_server` / `GITLAB_INVESTIGATE_TOOLS` references in removed tests

**Add:**
- `TestConfig::test_github_investigate_tools_are_read_only` — same pattern as existing write-verb check, applied to `GITHUB_INVESTIGATE_TOOLS`

**Update:**
- `TestRunPhase::_make_trace()`: `Trace(repo="test/proj", pr_number=1, github_pr="test/proj#1")`
- Remove `project_id` and `pipeline_id` kwargs from all `Trace(...)` calls in tests

## Investigation report schema

`pipeline_id` field holds the GitHub Actions run ID (string). All other fields unchanged. `format_ci_report` requires no changes.

## No changes to

- `tools/local.py`
- `run_phase()` loop logic
- `GITHUB_ACT_TOOLS`
- `github_mcp_server()`
- `ACT_SYSTEM`
- `.github/workflows/ci.yml`
