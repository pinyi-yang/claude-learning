# The LLM API — understand the primitive
Before "agents," just get fluent with the raw API. The key insight is that an LLM call is stateless — it's just a function: messages[] → response. Everything agents do is built on top of this.
What to build: A simple Python script that calls the Anthropic API, passes a conversation history, and prints the response. Add streaming. Understand system, user, and assistant roles deeply.
```python
import anthropic

client = anthropic.Anthropic()
messages = [{"role": "user", "content": "Explain what a CI pipeline does in 2 sentences."}]

response = client.messages.create(
    model="claude-opus-4-5",
    max_tokens=1024,
    system="You are a DevOps expert.",
    messages=messages
)
print(response.content[0].text)
```

![hello-tool-structure](hello-tool-structure.png)

Key thing to internalize: The model has no memory between calls. You, the developer, are responsible for maintaining state.

## Tool use — giving the model hands
This is the single most important concept. Tool use (also called "function calling") is how an LLM goes from a text generator to something that can act. The pattern:

1. You describe tools to the model (name, description, input schema)
2. The model decides to call one and returns a structured tool_use block
3. Your code executes the tool and returns the result
4. The model sees the result and continues

What to build: An agent with two tools — get_git_log(repo_path) and check_disk_usage(path). Ask it "is this repo healthy?" and watch it decide which tools to call.
The critical mental model here: the model never actually runs code. It just outputs JSON describing what it wants to call. Your code is the executor. You're always in control.

## The agentic loop — putting it together
Once you have tool use, an "agent" is just a while loop:
```
while True:
    response = call_llm(messages)
    if response wants to use a tool:
        result = run_tool(response.tool_call)
        messages.append(tool_result)
    else:
        break  # model is done
```

That's it. Everything else — memory systems, multi-agent orchestration, RAG — is layered on top of this loop. Getting this loop solid in your head before adding complexity is the most valuable thing you can do.
What to build: A "DevOps assistant" that loops until it can fully answer "what's the status of my system?" — calling multiple tools across multiple turns before giving a final summary.

## Prompt engineering for agents
Agents are far more sensitive to system prompt quality than one-shot completions. As a senior engineer, you'll be tempted to under-specify — resist that. Your system prompt needs to cover:

- Role & goal — what the agent is and what success looks like
- Tool guidance — when to use each tool, and when not to
- Output format — especially for structured data
- Failure handling — what to do when a tool returns an error

The Anthropic prompt engineering guide is worth reading in full at this stage.

## MCP — the connective tissue
Once your tool use is solid, MCP (Model Context Protocol) is the natural next step. It's the standardization layer that lets agents connect to any service — GitHub, Jira, Datadog, Slack — through a consistent interface, without writing custom glue for each one.
Since Claude Code itself runs on MCP, you're already using it. Understanding how to write an MCP server is what unlocks building production-grade DevOps agents that connect to your real infrastructure.

# Reason -- Action (ReAct)

## Four Types of State:
- **In-context memory** — just the message history you pass each turn. Simple, free, limited by the context window (~200k tokens for Claude). Fine for single sessions.
- **External memory (RAG)** — store facts in a vector DB or key-value store; retrieve relevant ones at query time and inject them into the system prompt. Used when: the agent needs to know things that do
- **Episodic memory** — save summaries of past agent runs to a file or DB. At the start of each new session, load relevant past episodes. Used when: you want the agent to remember "last Tuesday the disk usage alert was a false positive caused by log rotation."
- **Scratchpad memory** — give the agent a write_note(key, value) / read_note(key) tool. It manages its own working memory mid-run. Used when: the agent needs to track state across many tool calls without bloating the message history (e.g. tracking which hosts it's already checked during an incident sweep).

Once a single agent + tool loop isn't enough, you compose agents. Two primary topologies:
Orchestrator → subagents — one "manager" agent breaks down a task and delegates to specialist agents.

## How these compose in practice
A production incident triage agent uses all four:

Tool use — calls PagerDuty, Datadog, your runbook store, Slack
ReAct — reasons about what to check next based on what it found
Memory — retrieves past similar incidents from a vector store; writes a scratchpad note when it confirms a hypothesis
Multi-agent — spawns a "log analysis" subagent and a "metrics analysis" subagent in parallel, then synthesizes their findings into a root-cause summary

![reAct-loop](reAct-loop.png)
The structural change from 01_hello_tool is small — same loop, same tools — but two things are new: the system prompt instructs explicit reasoning, and a Trace dataclass captures every thought/action/observation so you can inspect what the agent did and why. That's the thing that makes agents debuggable in production.