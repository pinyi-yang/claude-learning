# GitHub Actions CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a GitHub Actions workflow that runs the `agents/03_ci_cd` unit tests on every PR and push.

**Architecture:** Single `test` job in `.github/workflows/ci.yml`. Fix a broken import (`prompt.py` → `prompts.py`) that prevents test collection. Set `PYTHONPATH=agents/03_ci_cd` so bare imports in tests resolve without restructuring the module layout.

**Tech Stack:** GitHub Actions, Python 3.13, pytest, pip

---

## File Map

| Action | Path | Purpose |
|--------|------|---------|
| Rename | `agents/03_ci_cd/prompt.py` → `agents/03_ci_cd/prompts.py` | Fix broken import in `agent.py` and `tests/test_agent.py` |
| Create | `.github/workflows/ci.yml` | GitHub Actions workflow |

---

### Task 1: Fix the broken import by renaming prompt.py

**Files:**
- Rename: `agents/03_ci_cd/prompt.py` → `agents/03_ci_cd/prompts.py`

The test file imports `from prompts import ...` transitively via `from agent import ...`. The module is saved as `prompt.py`, so pytest fails at collection time with `ModuleNotFoundError: No module named 'prompts'`. The file contents are correct — only the filename needs to change.

- [ ] **Step 1: Rename the file**

```bash
git mv agents/03_ci_cd/prompt.py agents/03_ci_cd/prompts.py
```

- [ ] **Step 2: Verify tests now collect**

```bash
cd agents/03_ci_cd && PYTHONPATH=. python -m pytest tests/ --collect-only
```

Expected output (all tests collected, no errors):
```
collected 13 items

tests/test_agent.py::TestFormatCiReport::test_formats_basic_report
tests/test_agent.py::TestFormatCiReport::test_includes_log_lines_when_requested
...
```

- [ ] **Step 3: Run the tests to confirm they pass**

```bash
cd agents/03_ci_cd && PYTHONPATH=. python -m pytest tests/ -v
```

Expected: all 13 tests PASS (config tests that require tokens will pass because `monkeypatch` handles env vars).

- [ ] **Step 4: Commit**

```bash
git add agents/03_ci_cd/prompts.py
git commit -m "fix: rename prompt.py to prompts.py to match import"
```

---

### Task 2: Add the GitHub Actions workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create the workflows directory**

```bash
mkdir -p .github/workflows
```

- [ ] **Step 2: Write the workflow file**

Create `.github/workflows/ci.yml` with this exact content:

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run tests
        run: pytest agents/03_ci_cd/tests/ -v
        env:
          PYTHONPATH: agents/03_ci_cd
```

- [ ] **Step 3: Validate the YAML is well-formed**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo "YAML valid"
```

Expected: `YAML valid`

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add GitHub Actions workflow to run agent unit tests on PR"
```

---

## Self-Review

**Spec coverage:**
- [x] `.github/workflows/ci.yml` created — Task 2
- [x] Triggers on `push` and `pull_request` — Task 2 Step 2
- [x] Python 3.13, `ubuntu-latest` — Task 2 Step 2
- [x] `pip install -r requirements.txt` — Task 2 Step 2
- [x] `pytest agents/03_ci_cd/tests/ -v` with `PYTHONPATH=agents/03_ci_cd` — Task 2 Step 2
- [x] `prompt.py` → `prompts.py` rename — Task 1

**Placeholders:** None.

**Type consistency:** No shared types across tasks — tasks are independent file operations.
