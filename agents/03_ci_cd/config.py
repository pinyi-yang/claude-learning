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
