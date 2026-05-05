# GitHub Actions Investigator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the agent's GitLab Phase 1 with GitHub Actions investigation, so the agent takes `(repo, pr_number)` and triages GitHub Actions CI failures on a PR.

**Architecture:** Swap `config.py` tool lists and MCP server reference, update `Trace` fields and `run_agent()` signature in `agent.py`, rewrite `INVESTIGATE_SYSTEM` in `prompts.py`. Phase 2 (GitHub write tools) and `tools/local.py` are untouched.

**Tech Stack:** Python 3.11+, Anthropic SDK (Bedrock), GitHub MCP server (`api.githubcopilot.com/mcp/`), pytest

---

## File Map

| Action | Path | Change |
|--------|------|--------|
| Modify | `agents/03_ci_cd/config.py` | Remove GitLab; add `GITHUB_INVESTIGATE_TOOLS` |
| Modify | `agents/03_ci_cd/prompts.py` | Rewrite `INVESTIGATE_SYSTEM` |
| Modify | `agents/03_ci_cd/agent.py` | Update `Trace`, `run_agent()`, imports, docstring |
| Modify | `agents/03_ci_cd/tests/test_agent.py` | Remove GitLab tests; add GitHub investigate test; fix `_make_trace()` |

---

### Task 1: Update config.py — replace GitLab with GitHub investigate tools

**Files:**
- Modify: `agents/03_ci_cd/config.py`
- Test: `agents/03_ci_cd/tests/test_agent.py`

The current `config.py` exports `gitlab_mcp_server`, `GITLAB_INVESTIGATE_TOOLS`, `github_mcp_server`, and `GITHUB_ACT_TOOLS`. We're removing the GitLab pieces and adding `GITHUB_INVESTIGATE_TOOLS`.

- [ ] **Step 1: Write the failing tests first**

Open `agents/03_ci_cd/tests/test_agent.py`. Replace the entire `TestConfig` class with:

```python
class TestConfig:
    def test_github_investigate_tools_are_read_only(self):
        """Ensure no write tools sneak into the investigation allowlist."""
        from config import GITHUB_INVESTIGATE_TOOLS
        write_indicators = ["create", "update", "delete", "post", "approve"]
        for tool in GITHUB_INVESTIGATE_TOOLS:
            for indicator in write_indicators:
                assert indicator not in tool.lower(), (
                    f"Write tool '{tool}' found in GITHUB_INVESTIGATE_TOOLS — "
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

    def test_github_server_requires_token(self, monkeypatch):
        from config import github_mcp_server
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with pytest.raises(ValueError, match="GITHUB_TOKEN"):
            github_mcp_server(GITHUB_ACT_TOOLS)

    def test_github_server_shape(self, monkeypatch):
        from config import github_mcp_server
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        server = github_mcp_server(["actions_list"])
        assert server["type"] == "url"
        assert "github" in server["url"]
        assert server["allowed_tools"] == ["actions_list"]
        assert "authorization_token" in server
```

Also update the top-level import in the test file (lines 17-20) — replace:
```python
from config import (
    GITLAB_INVESTIGATE_TOOLS,
    GITHUB_ACT_TOOLS,
)
```
with:
```python
from config import (
    GITHUB_INVESTIGATE_TOOLS,
    GITHUB_ACT_TOOLS,
)
```

- [ ] **Step 2: Run tests to verify they fail as expected**

```bash
cd agents/03_ci_cd && PYTHONPATH=. python -m pytest tests/test_agent.py::TestConfig -v
```

Expected: `ImportError` or `FAILED` — `GITHUB_INVESTIGATE_TOOLS` doesn't exist yet.

- [ ] **Step 3: Implement the config changes**

Replace the entire content of `agents/03_ci_cd/config.py` with:

```python
"""
config.py — MCP server configuration and tool allowlists.

Centralising this here means:
  - Swapping a MCP server URL is a one-line change
  - Tool allowlists are version-controlled and reviewable
  - Adding a new phase (e.g. "remediate") is adding one list here
"""

import os
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# MCP server definitions
# ---------------------------------------------------------------------------

def github_mcp_server(allowed_tools: list[str]) -> dict:
    """
    GitHub MCP server config for the Anthropic API.

    Auth: GitHub personal access token with repo scope.
    """
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN not set in environment.")

    return {
        "type": "url",
        "url": "https://api.githubcopilot.com/mcp/",
        "name": "github",
        "allowed_tools": allowed_tools,
        "authorization_token": token,
    }


# ---------------------------------------------------------------------------
# Tool allowlists — each phase only sees the tools it needs.
#
# PRINCIPLE: investigation phase is read-only, act phase is write-only.
# The model literally cannot post a comment during investigation.
# ---------------------------------------------------------------------------

# Phase 1: understand what failed in GitHub Actions
GITHUB_INVESTIGATE_TOOLS = [
    "actions_list",   # list workflow runs for the PR; list jobs within a run
    "actions_get",    # get details of a specific run or job
    "get_job_logs",   # fetch raw log content for a failed job
]

# Phase 2: report findings
GITHUB_ACT_TOOLS = [
    "create_pull_request_review",         # post a structured review
    "add_pull_request_review_comment",    # inline comment on specific line
    "create_issue",                       # fallback: open an issue instead
]

# For local tools (non-MCP) that supplement the agent
LOCAL_TOOLS = [
    "format_ci_report",    # formats findings into a structured comment body
]
```

- [ ] **Step 4: Run the config tests to verify they pass**

```bash
cd agents/03_ci_cd && PYTHONPATH=. python -m pytest tests/test_agent.py::TestConfig -v
```

Expected: all 4 `TestConfig` tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/03_ci_cd/config.py agents/03_ci_cd/tests/test_agent.py
git commit -m "feat: replace GitLab config with GitHub Actions investigate tools"
```

---

### Task 2: Rewrite INVESTIGATE_SYSTEM prompt

**Files:**
- Modify: `agents/03_ci_cd/prompts.py`

No tests cover prompt content directly (prompts are evaluated at runtime). The change here is correctness for the model — wrong prompt = wrong behavior at runtime.

- [ ] **Step 1: Replace INVESTIGATE_SYSTEM in prompts.py**

Open `agents/03_ci_cd/prompts.py`. Replace the `INVESTIGATE_SYSTEM` string (lines 10–51) with:

```python
INVESTIGATE_SYSTEM = """You are a CI/CD triage specialist with read access to GitHub Actions.

Your job: given a GitHub repo and PR number, determine exactly what failed and why.

## Investigation strategy
Follow this order — don't skip steps:
1. List recent workflow runs for the PR — find the latest failed run
2. List jobs in that run to identify which ones failed
3. For each failed job: fetch its logs and find the root cause
4. Identify: is this a flaky test, a real regression, an infra issue, or a config problem?

## Log analysis rules
- Logs can be large. Look for ERROR, FAILED, exception tracebacks, exit codes.
- Distinguish: did the job fail because of the code, or because of the environment?
- Note the exact failing test name, command, or line if visible.

## Reasoning
Think step by step before each tool call. State what you're looking for and why.
After each observation, update your hypothesis before proceeding.

## Output format
When investigation is complete, output a structured JSON block:
```json
{
  "pipeline_id": "<actions_run_id>",
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
  "summary": "One sentence plain-English summary for the PR comment.",
  "recommendation": "What the author should do next."
}
```

Do not post any comments or take any write actions. Investigation only.
"""
```

Leave `ACT_SYSTEM` and the module docstring unchanged.

- [ ] **Step 2: Verify the file is importable**

```bash
cd agents/03_ci_cd && python -c "from prompts import INVESTIGATE_SYSTEM, ACT_SYSTEM; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Run the full test suite to confirm no regressions**

```bash
cd agents/03_ci_cd && PYTHONPATH=. python -m pytest tests/ -v
```

Expected: same pass/fail count as before this task (16 pass, 2 pre-existing failures).

- [ ] **Step 4: Commit**

```bash
git add agents/03_ci_cd/prompts.py
git commit -m "feat: rewrite INVESTIGATE_SYSTEM for GitHub Actions"
```

---

### Task 3: Update agent.py — Trace fields and run_agent() signature

**Files:**
- Modify: `agents/03_ci_cd/agent.py`
- Test: `agents/03_ci_cd/tests/test_agent.py`

Three changes in `agent.py`:
1. Fix imports (remove `gitlab_mcp_server`, `GITLAB_INVESTIGATE_TOOLS`)
2. Rename `Trace` fields: `project_id` → `repo`, `pipeline_id` → `pr_number` (int)
3. Rewrite `run_agent()` to take `(repo, pr_number)` and use `GITHUB_INVESTIGATE_TOOLS`

And one change in tests: fix `_make_trace()` and all `Trace(...)` calls.

- [ ] **Step 1: Update the test helpers first**

In `agents/03_ci_cd/tests/test_agent.py`, find and update `_make_trace()` inside `TestRunPhase` (around line 178):

Replace:
```python
def _make_trace(self):
    return Trace(project_id="test/proj", pipeline_id="999", github_pr="test/proj#1")
```
With:
```python
def _make_trace(self):
    return Trace(repo="test/proj", pr_number=1, github_pr="test/proj#1")
```

- [ ] **Step 2: Run phase tests to verify they fail**

```bash
cd agents/03_ci_cd && PYTHONPATH=. python -m pytest tests/test_agent.py::TestRunPhase -v
```

Expected: `TypeError` — `Trace` doesn't accept `repo`/`pr_number` yet.

- [ ] **Step 3: Update imports in agent.py**

In `agents/03_ci_cd/agent.py`, replace lines 33–38:
```python
from config import (
    gitlab_mcp_server,
    github_mcp_server,
    GITLAB_INVESTIGATE_TOOLS,
    GITHUB_ACT_TOOLS,
)
```
With:
```python
from config import (
    github_mcp_server,
    GITHUB_INVESTIGATE_TOOLS,
    GITHUB_ACT_TOOLS,
)
```

- [ ] **Step 4: Update the Trace dataclass**

In `agents/03_ci_cd/agent.py`, replace the `Trace` dataclass (lines 58–104):

```python
@dataclass
class Trace:
    repo: str
    pr_number: int
    github_pr: str
    steps: list[Step] = field(default_factory=list)
    investigation_report: dict | None = None  # structured JSON from phase 1
    comment_posted: bool = False

    def add(self, step: Step) -> None:
        self.steps.append(step)

    def phase_steps(self, phase: str) -> list[Step]:
        return [s for s in self.steps if s.phase == phase]

    def to_dict(self) -> dict:
        return {
            "repo": self.repo,
            "pr_number": self.pr_number,
            "github_pr": self.github_pr,
            "investigation_report": self.investigation_report,
            "comment_posted": self.comment_posted,
            "steps": [
                {
                    "kind": s.kind,
                    "phase": s.phase,
                    "content": s.content[:500],  # truncate for storage
                    "tool_name": s.tool_name,
                }
                for s in self.steps
            ],
        }

    def pretty_print(self) -> None:
        print(f"\n{'='*60}")
        print(f"TRACE — repo={self.repo} pr=#{self.pr_number}")
        for step in self.steps:
            tag = f"[{step.phase.upper()}:{step.kind.upper()}]"
            if step.kind == "thought":
                print(f"\n{tag}\n  {step.content[:300]}")
            elif step.kind == "action":
                print(f"\n{tag} {step.tool_name}({json.dumps(step.tool_input)[:200]})")
            elif step.kind == "observation":
                print(f"\n{tag}\n  {step.content[:300]}")
            elif step.kind == "answer":
                print(f"\n{tag}\n  {step.content[:300]}")
        print("="*60)
```

- [ ] **Step 5: Rewrite run_agent()**

In `agents/03_ci_cd/agent.py`, replace the entire `run_agent()` function and docstring (lines 235–335) with:

```python
def run_agent(
    repo: str,
    pr_number: int,
    verbose: bool = True,
) -> Trace:
    """
    Full CI triage run:
      Phase 1 — investigate: what failed in the GitHub Actions run?
      Phase 2 — act: post findings as a GitHub PR comment

    Args:
        repo:       GitHub repo in "owner/repo" format (e.g. "myorg/myrepo")
        pr_number:  PR number to investigate and comment on
    """
    client = anthropic.AnthropicBedrock(aws_region=os.environ.get("AWS_REGION", "us-west-2"))

    trace = Trace(
        repo=repo,
        pr_number=pr_number,
        github_pr=f"{repo}#{pr_number}",
    )

    # ------------------------------------------------------------------
    # Phase 1: Investigate
    # Only GitHub read tools visible — model cannot write anything
    # ------------------------------------------------------------------
    print("\n" + "="*60)
    print("PHASE 1: INVESTIGATE")
    print("="*60)

    investigate_prompt = (
        f"Investigate the GitHub Actions CI failures on PR #{pr_number} "
        f"in repo '{repo}'. Find the most recent failed workflow run, "
        f"identify which jobs failed and why, and produce the structured JSON report."
    )

    investigate_messages = [{"role": "user", "content": investigate_prompt}]

    investigation_result = run_phase(
        client=client,
        system=INVESTIGATE_SYSTEM,
        messages=investigate_messages,
        mcp_servers=[github_mcp_server(GITHUB_INVESTIGATE_TOOLS)],
        phase="investigate",
        trace=trace,
        max_iterations=8,
        max_tool_calls=6,
    )

    # Extract JSON from the investigation result
    # PRODUCTION PITFALL: models sometimes wrap JSON in markdown fences.
    report_json = investigation_result
    if "```json" in report_json:
        report_json = report_json.split("```json")[1].split("```")[0].strip()
    elif "```" in report_json:
        report_json = report_json.split("```")[1].split("```")[0].strip()

    try:
        trace.investigation_report = json.loads(report_json)
        print(f"\nInvestigation complete: {trace.investigation_report.get('summary', '')}")
    except json.JSONDecodeError:
        print(f"\nWarning: could not parse investigation JSON. Raw result:\n{investigation_result[:500]}")
        report_json = json.dumps({"summary": investigation_result, "failed_jobs": [], "pipeline_id": "unknown"})

    # ------------------------------------------------------------------
    # Phase 2: Act
    # Only GitHub write tools visible — model cannot read anymore
    # ------------------------------------------------------------------
    print("\n" + "="*60)
    print("PHASE 2: ACT")
    print("="*60)

    act_prompt = (
        f"Post a CI triage report as a comment on GitHub PR #{pr_number} "
        f"in repo '{repo}'.\n\n"
        f"Investigation findings:\n```json\n{report_json}\n```\n\n"
        f"Use format_ci_report to format the comment body, then post it."
    )

    act_messages = [{"role": "user", "content": act_prompt}]

    act_result = run_phase(
        client=client,
        system=ACT_SYSTEM,
        messages=act_messages,
        mcp_servers=[github_mcp_server(GITHUB_ACT_TOOLS)],
        phase="act",
        trace=trace,
        max_iterations=4,
        max_tool_calls=3,
    )

    trace.comment_posted = "posted" in act_result.lower() or "comment" in act_result.lower()
    print(f"\nComment posted: {trace.comment_posted}")

    return trace
```

- [ ] **Step 6: Update the module docstring**

At the top of `agents/03_ci_cd/agent.py`, replace the Architecture comment block (lines 12–21):

```python
"""
03_cicd_monitor — two-phase CI/CD triage agent using Anthropic MCP proxy.

New patterns vs 02_react_loop:
  1. MCP servers passed directly to Anthropic API — no TOOL_REGISTRY for MCP tools
  2. Two-phase loop: investigate (read-only GitHub Actions) → act (write GitHub)
  3. Tool allowlisting per phase — model only sees tools it's allowed to use
  4. Local tools alongside MCP tools — format_ci_report runs in your process
  5. Phase handoff via structured JSON — investigation result feeds action prompt

Architecture:
  Phase 1 (investigate):
    - MCP: github (3 read-only Actions tools)
    - Local: none
    - Goal: produce structured JSON report of failures

  Phase 2 (act):
    - MCP: github (3 write tools)
    - Local: format_ci_report
    - Goal: post formatted comment to GitHub PR
"""
```

- [ ] **Step 7: Update the entry point**

In `agents/03_ci_cd/agent.py`, replace the `if __name__ == "__main__":` block (lines 342–371):

```python
if __name__ == "__main__":
    import sys

    # Usage: python agent.py <repo> <pr_number>
    # Example: python agent.py pinyi-yang/claude-learning 4
    if len(sys.argv) < 3:
        print("Usage: python agent.py <repo> <pr_number>")
        print("Example: python agent.py pinyi-yang/claude-learning 4")
        sys.exit(1)

    repo = sys.argv[1]
    pr_number = int(sys.argv[2])

    trace = run_agent(repo=repo, pr_number=pr_number)

    trace.pretty_print()

    import json as _json
    from pathlib import Path
    trace_path = Path(f"trace_pr{pr_number}.json")
    trace_path.write_text(_json.dumps(trace.to_dict(), indent=2))
    print(f"\nTrace saved: {trace_path}")
```

- [ ] **Step 8: Run the full test suite**

```bash
cd agents/03_ci_cd && PYTHONPATH=. python -m pytest tests/ -v
```

Expected: 16 pass, 2 pre-existing failures (`test_gitlab_investigate_tools_are_read_only` is now gone — replaced by `test_github_investigate_tools_are_read_only` which should pass; the 2 remaining failures are `test_local_tool_executed_by_agent` and nothing else unexpected).

Check total count: should now be **17 pass, 1 pre-existing failure** (the GitLab read-only test is removed; `test_github_investigate_tools_are_read_only` passes; `test_local_tool_executed_by_agent` still fails).

- [ ] **Step 9: Commit**

```bash
git add agents/03_ci_cd/agent.py agents/03_ci_cd/tests/test_agent.py
git commit -m "feat: update Trace and run_agent() for GitHub Actions investigation"
```

---

## Self-Review

**Spec coverage:**
- [x] Remove `gitlab_mcp_server()` and `GITLAB_INVESTIGATE_TOOLS` — Task 1
- [x] Add `GITHUB_INVESTIGATE_TOOLS` with `actions_list`, `actions_get`, `get_job_logs` — Task 1
- [x] Rewrite `INVESTIGATE_SYSTEM` for GitHub Actions — Task 2
- [x] `Trace` fields: `repo: str`, `pr_number: int` — Task 3
- [x] `run_agent(repo, pr_number)` signature — Task 3
- [x] Phase 1 uses `github_mcp_server(GITHUB_INVESTIGATE_TOOLS)` — Task 3
- [x] Remove GitLab config tests — Task 1
- [x] Add `test_github_investigate_tools_are_read_only` — Task 1
- [x] Fix `_make_trace()` — Task 3
- [x] `format_ci_report`, `tools/local.py`, Phase 2 — explicitly untouched ✓

**Placeholder scan:** No TBDs. All code blocks are complete.

**Type consistency:**
- `Trace(repo=..., pr_number=..., github_pr=...)` used consistently in Task 3 Steps 1 and 4
- `GITHUB_INVESTIGATE_TOOLS` defined in Task 1 Step 3, imported in Task 3 Step 3
- `github_mcp_server()` unchanged throughout — no rename
