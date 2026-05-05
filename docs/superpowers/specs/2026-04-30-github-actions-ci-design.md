---
title: GitHub Actions CI for agent unit tests
date: 2026-04-30
status: approved
---

## Goal

Run the `agents/03_ci_cd` unit tests automatically on every PR and push, with no secrets required.

## Deliverables

1. `.github/workflows/ci.yml` — GitHub Actions workflow
2. Rename `agents/03_ci_cd/prompt.py` → `agents/03_ci_cd/prompts.py` — fixes broken import in both `agent.py` and `tests/test_agent.py`

## Workflow design

**File:** `.github/workflows/ci.yml`

**Triggers:** `push` and `pull_request` on all branches.

**Job: `test`**
- Runner: `ubuntu-latest`
- Python: `3.13`
- Steps:
  1. `actions/checkout@v4`
  2. `actions/setup-python@v5` with `python-version: '3.13'`
  3. `pip install -r requirements.txt`
  4. `pytest agents/03_ci_cd/tests/ -v` with `PYTHONPATH=agents/03_ci_cd`

**No secrets needed** — all Anthropic, GitLab, and GitHub API calls are mocked in the test suite.

## Why PYTHONPATH instead of conftest.py

The test file uses bare imports (`from tools.local`, `from agent`, `from config`) that assume the working directory is `agents/03_ci_cd/`. Setting `PYTHONPATH=agents/03_ci_cd` in the pytest env satisfies these imports without adding a `conftest.py` or restructuring the module layout.

## Bug fix rationale

`agent.py` imports `from prompts import ...` and `tests/test_agent.py` imports `from agent import ...` (which transitively needs `prompts`). The file was saved as `prompt.py`, breaking both. Renaming to `prompts.py` is the minimal fix.
