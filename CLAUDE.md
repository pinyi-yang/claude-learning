# AI Agent Learning Project

## Context
Senior software engineer learning AI agent development, with a focus on DevOps and 
project management automation. Using Claude Code as the primary learning guide.

## Goals
- Understand agent patterns: ReAct, tool use, memory, multi-agent orchestration
- Build practical agents: CI/CD monitoring, IaC review, incident triage, Jira/GitHub automation
- Learn evaluation, observability, and production-readiness for agents
- Prefer Python with the Anthropic SDK; open to TypeScript for tooling

## How to Guide Me
- Explain the "why" before the "how" — I want mental models, not just code
- Scaffold progressively: minimal working example first, then extend
- When I ask to build something, propose an architecture before writing code
- Flag anti-patterns and production pitfalls inline as code comments
- After each working prototype, suggest a "what to try next" challenge

## Code Conventions
- Python 3.11+, `uv` for package management, `ruff` for linting
- Type hints on all functions; docstrings on public interfaces
- Keep agent logic separated from tool/integration code
- Use `.env` + `python-dotenv`; never hardcode keys
- Tests go in `tests/`; use `pytest`

## Project Structure
agent-learning/
├── CLAUDE.md              ← this file
├── docs/                  ← reference docs, runbooks, architecture notes
├── agents/                ← one folder per agent project
│   ├── 01_hello_tool/
│   ├── 02_react_loop/
│   └── 03_cicd_monitor/
├── tools/                 ← reusable tool definitions
├── evals/                 ← evaluation harnesses
└── notes/                 ← my learning notes, gotchas, open questions

## Current Focus
[x] Phase 1: Tool use basics — build a simple agent that calls real APIs
[ ] Phase 2: ReAct loop — implement think → act → observe cycle manually
[ ] Phase 3: First DevOps agent — GitHub PR review bot
[ ] Phase 4: Multi-agent — orchestrator + specialist subagents

## Reference Material (in docs/)
- anthropic_agent_patterns.md   — Anthropic's recommended patterns
- devops_runbooks/              — Sample runbooks for incident triage agent
- tool_catalog.md               — Inventory of tools I'm building