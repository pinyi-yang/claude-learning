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

def gitlab_mcp_server(allowed_tools: list[str]) -> dict:
    """
    GitLab MCP server config for the Anthropic API.

    Auth: GitLab personal access token with read_api scope.
    Docs: https://gitlab.com/gitlab-org/gitlab-mcp
    """
    token = os.getenv("GITLAB_TOKEN")
    if not token:
        raise ValueError("GITLAB_TOKEN not set in environment.")

    return {
        "type": "url",
        "url": "https://gitlab.com/api/mcp",   # GitLab's hosted MCP endpoint
        "name": "gitlab",
        "allowed_tools": allowed_tools,
        # Auth header — GitLab MCP uses Bearer token
        "authorization_token": token,
    }


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
# Tool allowlists — the core of our tool limitation strategy.
#
# PRINCIPLE: each phase only sees the tools it needs.
#   - Investigation phase: read-only GitLab tools
#   - Action phase: write-only GitHub tools
#
# This enforces a trust boundary in code, not just in prompts.
# The model literally cannot post a comment during investigation.
# ---------------------------------------------------------------------------

# Phase 1: understand what failed
GITLAB_INVESTIGATE_TOOLS = [
    "list_project_pipelines",   # find recent pipelines for a project
    "get_pipeline",             # status, stages, timing for one pipeline
    "list_pipeline_jobs",       # jobs within a pipeline
    "get_job_log",              # raw log for a specific job
    "list_merge_requests",      # find the MR that triggered this pipeline
]

# Phase 2: report findings
GITHUB_ACT_TOOLS = [
    "create_pull_request_review",   # post a structured review
    "add_pull_request_review_comment",  # inline comment on specific line
    "create_issue",                 # fallback: open an issue instead
]

# For local tools (non-MCP) that supplement the agent
# These are defined in tools/local.py and passed as regular tools
LOCAL_TOOLS = [
    "format_ci_report",    # formats findings into a structured comment body
]