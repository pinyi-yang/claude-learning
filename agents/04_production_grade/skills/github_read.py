"""
skills/github_read.py — GitHub read skills.

SKILL: fetch_pr_context
-----------------------
Composes 3 GitHub API calls into 1 agent tool:
  1. GET /repos/{repo}/pulls/{pr_number}       → title, description, author
  2. GET /repos/{repo}/pulls/{pr_number}/files → changed file list
  3. GET /repos/{repo}/pulls/{pr_number}       → diff (via Accept header)

WHY ONE SKILL INSTEAD OF 3 TOOLS?
----------------------------------
If you gave the agent 3 separate tools, it would:
  - Use 3 tool calls (context window cost)
  - Make 3 decisions (more chances to call in wrong order)
  - Sometimes skip one (model decides it's not needed)

With 1 skill, the agent makes 1 decision: "I need PR context."
Your code handles the sequencing reliably every time.

This is the core skill pattern: hide orchestration from the model,
expose intent.
"""

from __future__ import annotations
import json
import httpx
from .base import Skill, SkillResult


class FetchPRContextSkill(Skill):
    """
    Fetches everything the agent needs to review a PR in one call.
    Returns a unified context block: metadata + file list + diff.
    """

    def __init__(self, github_token: str):
        self._token = github_token
        self._headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @property
    def name(self) -> str:
        return "fetch_pr_context"

    @property
    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "Fetches complete context for a GitHub pull request: "
                "title, description, author, changed files, and the full diff. "
                "Always call this first before reviewing a PR."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "GitHub repo in 'owner/repo' format.",
                    },
                    "pr_number": {
                        "type": "integer",
                        "description": "Pull request number.",
                    },
                },
                "required": ["repo", "pr_number"],
            },
        }

    def execute(self, repo: str, pr_number: int) -> SkillResult:
        """Fetch PR metadata, file list, and diff. Return as unified context."""
        try:
            # Step 1: PR metadata
            meta = self._get_pr_metadata(repo, pr_number)
            if meta is None:
                return SkillResult.error(f"PR #{pr_number} not found in {repo}")

            # Step 2: Changed files
            files = self._get_changed_files(repo, pr_number)

            # Step 3: Diff
            diff = self._get_diff(repo, pr_number)

            # Compose into a single context block
            context = self._format_context(meta, files, diff)

            return SkillResult.ok(
                content=context,
                pr_title=meta.get("title"),
                file_count=len(files),
                diff_size=len(diff),
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return SkillResult.error("GitHub auth failed — check your GITHUB_TOKEN and scopes.")
            if e.response.status_code == 404:
                return SkillResult.error(f"Not found: {repo} PR #{pr_number}. Check repo name and PR number.")
            return SkillResult.error(f"GitHub API error {e.response.status_code}: {e.response.text[:200]}")
        except httpx.RequestError as e:
            return SkillResult.error(f"Network error reaching GitHub: {e}")

    def _get_pr_metadata(self, repo: str, pr_number: int) -> dict | None:
        resp = httpx.get(
            f"https://api.github.com/repos/{repo}/pulls/{pr_number}",
            headers=self._headers,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def _get_changed_files(self, repo: str, pr_number: int) -> list[dict]:
        resp = httpx.get(
            f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files",
            headers=self._headers,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def _get_diff(self, repo: str, pr_number: int) -> str:
        resp = httpx.get(
            f"https://api.github.com/repos/{repo}/pulls/{pr_number}",
            headers={**self._headers, "Accept": "application/vnd.github.diff"},
            timeout=15,
        )
        resp.raise_for_status()
        diff = resp.text

        # PRODUCTION PITFALL: large diffs blow up the context window.
        # Truncate and warn rather than silently passing 100k tokens.
        max_chars = 12_000
        if len(diff) > max_chars:
            diff = diff[:max_chars] + f"\n\n... [diff truncated at {max_chars} chars] ..."

        return diff

    def _format_context(self, meta: dict, files: list[dict], diff: str) -> str:
        """Format all three pieces into a readable context block."""
        file_list = "\n".join(
            f"  {f['filename']} (+{f['additions']} -{f['deletions']})"
            for f in files[:30]  # cap at 30 files
        )
        if len(files) > 30:
            file_list += f"\n  ... and {len(files) - 30} more files"

        return f"""## PR #{meta['number']}: {meta['title']}

**Author:** {meta['user']['login']}
**Base → Head:** {meta['base']['ref']} ← {meta['head']['ref']}
**State:** {meta['state']}
**Description:**
{meta.get('body') or '(no description)'}

## Changed Files ({len(files)} total)
{file_list}

## Diff
{diff}
"""


class FetchExistingCommentsSkill(Skill):
    """
    Fetches existing review comments on a PR.
    Use to avoid repeating feedback already given.
    """

    def __init__(self, github_token: str):
        self._headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @property
    def name(self) -> str:
        return "fetch_existing_comments"

    @property
    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "Fetches existing review comments on a PR. "
                "Call this to avoid repeating feedback already given by other reviewers."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "owner/repo"},
                    "pr_number": {"type": "integer"},
                },
                "required": ["repo", "pr_number"],
            },
        }

    def execute(self, repo: str, pr_number: int) -> SkillResult:
        try:
            resp = httpx.get(
                f"https://api.github.com/repos/{repo}/pulls/{pr_number}/comments",
                headers=self._headers,
                timeout=15,
            )
            resp.raise_for_status()
            comments = resp.json()

            if not comments:
                return SkillResult.ok("No existing review comments.", comment_count=0)

            formatted = "\n\n".join(
                f"**{c['user']['login']}** on `{c.get('path', '?')}` line {c.get('line', '?')}:\n{c['body'][:300]}"
                for c in comments[:10]  # cap at 10
            )
            return SkillResult.ok(
                f"Existing comments ({len(comments)} total, showing first 10):\n\n{formatted}",
                comment_count=len(comments),
            )
        except httpx.HTTPStatusError as e:
            return SkillResult.error(f"GitHub API error {e.response.status_code}")
        except httpx.RequestError as e:
            return SkillResult.error(f"Network error: {e}")
