"""
tools/local.py — local tools that supplement MCP tools.

These handle things MCP servers don't: local formatting, config reading,
report shaping. They're passed to the API as regular tool definitions
alongside the MCP server config.
"""

import json


# ---------------------------------------------------------------------------
# Tool schema definitions (passed to Anthropic API)
# ---------------------------------------------------------------------------

FORMAT_CI_REPORT_SCHEMA = {
    "name": "format_ci_report",
    "description": (
        "Formats a structured CI investigation JSON report into a GitHub PR comment body. "
        "Call this after investigation is complete and before posting to GitHub."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "report_json": {
                "type": "string",
                "description": "The JSON investigation report as a string.",
            },
            "include_log_lines": {
                "type": "boolean",
                "description": "Whether to include relevant log lines. Default false for brevity.",
                "default": False,
            },
        },
        "required": ["report_json"],
    },
}

LOCAL_TOOL_SCHEMAS = [FORMAT_CI_REPORT_SCHEMA]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def format_ci_report(report_json: str, include_log_lines: bool = False) -> str:
    """Format investigation JSON into a GitHub PR comment."""
    try:
        report = json.loads(report_json)
    except json.JSONDecodeError as e:
        return f"Error: could not parse report JSON: {e}"

    lines = []
    status_emoji = "❌" if report.get("status") == "failed" else "✅"

    lines.append(f"## {status_emoji} CI Pipeline Triage — Pipeline #{report.get('pipeline_id', 'unknown')}")
    lines.append("")
    lines.append(f"**Summary:** {report.get('summary', 'No summary provided.')}")
    lines.append("")

    failed_jobs = report.get("failed_jobs", [])
    if failed_jobs:
        lines.append("### Failed Jobs")
        lines.append("")
        lines.append("| Job | Failure Type | Root Cause | Confidence |")
        lines.append("|-----|-------------|------------|------------|")
        for job in failed_jobs:
            lines.append(
                f"| `{job.get('job_name', '?')}` "
                f"| {job.get('failure_type', '?')} "
                f"| {job.get('root_cause', '?')} "
                f"| {job.get('confidence', '?')} |"
            )
        lines.append("")

        if include_log_lines:
            for job in failed_jobs:
                log_lines = job.get("relevant_log_lines", [])
                if log_lines:
                    lines.append(f"<details><summary>Log excerpt: {job.get('job_name')}</summary>")
                    lines.append("")
                    lines.append("```")
                    lines.extend(log_lines[:20])  # cap at 20 lines
                    lines.append("```")
                    lines.append("</details>")
                    lines.append("")

    recommendation = report.get("recommendation")
    if recommendation:
        lines.append(f"**Next step:** {recommendation}")
        lines.append("")

    lines.append("---")
    lines.append("*Posted by CI triage agent*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool registry for local tools
# ---------------------------------------------------------------------------

LOCAL_TOOL_REGISTRY = {
    "format_ci_report": format_ci_report,
}


def execute_local_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a local (non-MCP) tool by name."""
    fn = LOCAL_TOOL_REGISTRY.get(tool_name)
    if fn is None:
        return f"Error: unknown local tool '{tool_name}'"
    try:
        return fn(**tool_input)
    except Exception as e:
        return f"Tool error: {type(e).__name__}: {e}"