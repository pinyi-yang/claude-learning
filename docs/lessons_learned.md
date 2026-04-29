1. The LLM API — understand the primitive
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

Key thing to internalize: The model has no memory between calls. You, the developer, are responsible for maintaining state.

2. Tool use — giving the model hands
This is the single most important concept. Tool use (also called "function calling") is how an LLM goes from a text generator to something that can act. The pattern:

1. You describe tools to the model (name, description, input schema)
2. The model decides to call one and returns a structured tool_use block
3. Your code executes the tool and returns the result
4. The model sees the result and continues

What to build: An agent with two tools — get_git_log(repo_path) and check_disk_usage(path). Ask it "is this repo healthy?" and watch it decide which tools to call.
The critical mental model here: the model never actually runs code. It just outputs JSON describing what it wants to call. Your code is the executor. You're always in control.

3. The agentic loop — putting it together
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

4. Prompt engineering for agents
Agents are far more sensitive to system prompt quality than one-shot completions. As a senior engineer, you'll be tempted to under-specify — resist that. Your system prompt needs to cover:

- Role & goal — what the agent is and what success looks like
- Tool guidance — when to use each tool, and when not to
- Output format — especially for structured data
- Failure handling — what to do when a tool returns an error

The Anthropic prompt engineering guide is worth reading in full at this stage.

5. MCP — the connective tissue
Once your tool use is solid, MCP (Model Context Protocol) is the natural next step. It's the standardization layer that lets agents connect to any service — GitHub, Jira, Datadog, Slack — through a consistent interface, without writing custom glue for each one.
Since Claude Code itself runs on MCP, you're already using it. Understanding how to write an MCP server is what unlocks building production-grade DevOps agents that connect to your real infrastructure.