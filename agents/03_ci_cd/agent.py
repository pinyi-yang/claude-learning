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
    - MCP: github (3 read-only tools for GitHub Actions)
    - Local: none
    - Goal: produce structured JSON report of failures

  Phase 2 (act):
    - MCP: github (3 write tools)
    - Local: format_ci_report
    - Goal: post formatted comment to GitHub PR
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Literal

import anthropic
from dotenv import load_dotenv

from config import (
    github_mcp_server,
    GITHUB_INVESTIGATE_TOOLS,
    GITHUB_ACT_TOOLS,
)
from prompts import INVESTIGATE_SYSTEM, ACT_SYSTEM
from tools.local import LOCAL_TOOL_SCHEMAS, execute_local_tool

load_dotenv()


# ---------------------------------------------------------------------------
# 1. Trace — same pattern as 02, extended for two phases
# ---------------------------------------------------------------------------

@dataclass
class Step:
    kind: Literal["thought", "action", "observation", "answer"]
    phase: Literal["investigate", "act"]
    content: str
    tool_name: str | None = None
    tool_input: dict | None = None


@dataclass
class Trace:
    project_id: str
    pipeline_id: str
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
            "project_id": self.project_id,
            "pipeline_id": self.pipeline_id,
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
        print(f"TRACE — project={self.project_id} pipeline={self.pipeline_id}")
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


# ---------------------------------------------------------------------------
# 2. MCP-aware loop
#
# Key difference from 02_react_loop:
#   - MCP tool_use blocks come back with type="tool_use" just like local tools
#   - BUT you don't execute them — Anthropic API already did
#   - You DO still execute local tools (format_ci_report) yourself
#   - The distinction: check if tool_name is in LOCAL_TOOL_REGISTRY
# ---------------------------------------------------------------------------

def run_phase(
    client: anthropic.Anthropic,
    system: str,
    messages: list[dict],
    mcp_servers: list[dict],
    phase: Literal["investigate", "act"],
    trace: Trace,
    max_iterations: int = 8,
    max_tool_calls: int = 6,  # code-enforced budget (lesson from 02!)
) -> str:
    """
    Run one phase of the agent loop.

    MCP tools are executed by Anthropic — we just record them.
    Local tools are executed by us — we execute and return results.

    Returns the final text answer from the model.
    """
    tool_call_count = 0
    iteration = 0

    while iteration < max_iterations:
        iteration += 1

        response = client.messages.create(
            model=os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
            max_tokens=2048,
            system=system,
            tools=LOCAL_TOOL_SCHEMAS,  # only local tools need explicit schema
            mcp_servers=mcp_servers,   # MCP tools are discovered automatically
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        local_tool_results = []

        for block in response.content:
            if block.type == "text" and block.text.strip():
                trace.add(Step(
                    kind="thought",
                    phase=phase,
                    content=block.text.strip(),
                ))
                print(f"\n[{phase.upper()}] THOUGHT: {block.text.strip()[:200]}")

            elif block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input

                # Code-enforced tool budget — from lesson in 02
                if tool_call_count >= max_tool_calls:
                    # Return a limiting message for local tools
                    # MCP tools: we can't stop them, but we can note it
                    print(f"\n[{phase.upper()}] BUDGET: tool call limit reached, skipping {tool_name}")
                    if tool_name in {s["name"] for s in LOCAL_TOOL_SCHEMAS}:
                        local_tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "Tool budget reached. Please conclude with available information.",
                        })
                    continue

                tool_call_count += 1
                trace.add(Step(
                    kind="action",
                    phase=phase,
                    content=f"{tool_name}({json.dumps(tool_input)[:200]})",
                    tool_name=tool_name,
                    tool_input=tool_input,
                ))
                print(f"\n[{phase.upper()}] ACTION ({tool_call_count}/{max_tool_calls}): {tool_name}")

                # Is this a local tool? Execute it ourselves.
                # Is it an MCP tool? Anthropic already executed it — we just record.
                local_schema_names = {s["name"] for s in LOCAL_TOOL_SCHEMAS}
                if tool_name in local_schema_names:
                    result = execute_local_tool(tool_name, tool_input)
                    trace.add(Step(
                        kind="observation",
                        phase=phase,
                        content=result,
                        tool_name=tool_name,
                    ))
                    local_tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
                    print(f"[{phase.upper()}] LOCAL RESULT: {result[:200]}")
                else:
                    # MCP tool — result will come back in next response automatically
                    # We record what was called for the trace
                    print(f"[{phase.upper()}] MCP TOOL — result handled by Anthropic API")

        # Feed local tool results back if any
        if local_tool_results:
            messages.append({"role": "user", "content": local_tool_results})

        if response.stop_reason == "end_turn":
            # Extract final text
            for block in response.content:
                if block.type == "text" and block.text.strip():
                    trace.add(Step(
                        kind="answer",
                        phase=phase,
                        content=block.text.strip(),
                    ))
                    return block.text.strip()
            return "(no text answer)"

    return "Error: max iterations reached."


# ---------------------------------------------------------------------------
# 3. Main agent — orchestrates both phases
# ---------------------------------------------------------------------------

def run_agent(
    project_id: str,
    pipeline_id: str,
    github_repo: str,
    github_pr_number: int,
    verbose: bool = True,
) -> Trace:
    """
    Full CI triage run:
      Phase 1 — investigate: what failed in the GitHub Actions workflow?
      Phase 2 — act: post findings as a GitHub PR comment

    Args:
        project_id:      GitHub repo in "owner/repo" format
        pipeline_id:     GitHub Actions workflow run ID
        github_repo:     GitHub repo in "owner/repo" format
        github_pr_number: PR number to comment on
    """
    client = anthropic.AnthropicBedrock(aws_region=os.environ.get("AWS_REGION", "us-west-2"))

    trace = Trace(
        project_id=project_id,
        pipeline_id=pipeline_id,
        github_pr=f"{github_repo}#{github_pr_number}",
    )

    # ------------------------------------------------------------------
    # Phase 1: Investigate
    # Only GitHub Actions read tools visible — model cannot write anything
    # ------------------------------------------------------------------
    print("\n" + "="*60)
    print("PHASE 1: INVESTIGATE")
    print("="*60)

    investigate_prompt = (
        f"Investigate GitHub Actions workflow run {pipeline_id} in repo '{project_id}'. "
        f"Determine what failed, why, and produce the structured JSON report."
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
    # Always strip them before parsing.
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
        # Continue anyway — the act phase will get the raw text
        report_json = json.dumps({"summary": investigation_result, "failed_jobs": [], "pipeline_id": pipeline_id})

    # ------------------------------------------------------------------
    # Phase 2: Act
    # Only GitHub write tools visible — model cannot read GitLab anymore
    # ------------------------------------------------------------------
    print("\n" + "="*60)
    print("PHASE 2: ACT")
    print("="*60)

    act_prompt = (
        f"Post a CI triage report as a comment on GitHub PR #{github_pr_number} "
        f"in repo '{github_repo}'.\n\n"
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
        max_tool_calls=3,  # tight budget — should only need 2 calls
    )

    trace.comment_posted = "posted" in act_result.lower() or "comment" in act_result.lower()
    print(f"\nComment posted: {trace.comment_posted}")

    return trace


# ---------------------------------------------------------------------------
# 4. Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    # Usage: python agent.py <project_id> <pipeline_id> <github_repo> <pr_number>
    # Example: python agent.py myorg/myrepo 12345678 myorg/myrepo 42
    if len(sys.argv) < 5:
        print("Usage: python agent.py <gitlab_project_id> <pipeline_id> <github_repo> <pr_number>")
        print("Example: python agent.py myorg/backend 98765432 myorg/backend 123")
        sys.exit(1)

    project_id = sys.argv[1]
    pipeline_id = sys.argv[2]
    github_repo = sys.argv[3]
    pr_number = int(sys.argv[4])

    trace = run_agent(
        project_id=project_id,
        pipeline_id=pipeline_id,
        github_repo=github_repo,
        github_pr_number=pr_number,
    )

    trace.pretty_print()

    # Save trace
    import json as _json
    from pathlib import Path
    trace_path = Path(f"trace_{pipeline_id}.json")
    trace_path.write_text(_json.dumps(trace.to_dict(), indent=2))
    print(f"\nTrace saved: {trace_path}")