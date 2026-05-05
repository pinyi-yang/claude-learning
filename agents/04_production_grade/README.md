# 04_pr_review_bedrock

PR review agent on AWS Bedrock using the **Skills pattern**.

## Key concepts introduced

### Skills vs raw tools

A **skill** is a multi-step capability exposed as a single tool.

| | Raw tools | Skills |
|---|---|---|
| `fetch_pr_context` | 3 separate tools (meta, files, diff) | 1 tool, 3 internal calls |
| Model decisions | 3 (call each tool in order?) | 1 (fetch PR context) |
| Context window | 3× tool schemas | 1× tool schema |
| Reusability | In this agent only | Across any agent |

### Why this solves the Bedrock/no-MCP problem

MCP servers are essentially remote skill hosts. Without MCP, skills
give you the same benefit — API complexity hidden behind a clean tool
interface — but running in your own process.

### The Skill base class pattern

```python
class MySkill(Skill):
    @property
    def name(self) -> str: return "my_skill"

    @property
    def schema(self) -> dict: return { ... }  # JSON schema

    def execute(self, **kwargs) -> SkillResult:
        # Do work, return SkillResult.ok(...) or SkillResult.error(...)
```

`SkillRegistry` handles routing, error catching, and schema assembly.
Your agent loop just calls `registry.execute(block.name, block.input)`.

## Setup

```bash
uv sync --extra dev

# AWS credentials (pick one):
#   Option A: aws configure (recommended)
#   Option B: .env file
echo "AWS_REGION=us-east-1" >> .env

# GitHub token (repo + pull_requests scopes)
echo "GITHUB_TOKEN=github_pat_xxxx" >> .env
```

## Run

```bash
uv run python agent.py <owner/repo> <pr_number>
uv run python agent.py myname/my-learning-project 3
```

## Test (no AWS or GitHub needed)

```bash
uv run pytest tests/ -v
```

## File structure

```
agent.py                # Bedrock loop, SkillRegistry wiring, Trace
config.py               # AnthropicBedrock client, model IDs
prompts.py              # system prompt (tune this for review quality)
skills/
  __init__.py
  base.py               # Skill, SkillResult, SkillRegistry — READ THIS FIRST
  github_read.py        # FetchPRContextSkill, FetchExistingCommentsSkill
  github_write.py       # PostReviewSkill (includes human approval gate)
tests/
  test_skills.py        # unit + integration, all mocked
```

## What to try next

1. **Write a new skill from scratch.** Add `FetchFileContextSkill(repo, path)`
   that fetches surrounding code for a changed file. Register it and update
   the system prompt. The agent should use it when a diff is ambiguous.

2. **Swap the model.** Change `MODEL = MODEL_HAIKU` in config.py.
   Run the same PR and compare quality vs cost. This is the model-tiering
   decision you'll make on every production agent.

3. **Extract the approval gate.** Move `_get_approval` out of PostReviewSkill
   into a standalone function in `agent.py`. Now you can pass different
   approval functions (terminal, auto, Slack webhook) without touching skill logic.

4. **Add a skill metadata log.** After each run, print a table:
   skill name | calls | success rate | avg result size (chars).
   This is the start of your per-skill observability.

5. **Build the eval harness.** Create `evals/fixtures/` with 3 sample diffs
   (one with a bug, one clean, one with a style issue). Assert the agent
   classifies each correctly. This is production-readiness checkpoint 1.