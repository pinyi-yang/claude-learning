"""
skills/github_write.py — GitHub write skills.

SKILL: post_review
------------------
Composes: format → human approval gate → GitHub API post

Notice the human gate lives INSIDE the skill, not in the agent loop.
This is a deliberate design choice for the prototype:

  Prototype: gate in the skill — simple, self-contained
  Production: gate as a separate async step — decoupled from skill

Either approach works. Putting it in the skill keeps the prototype
simple. Moving it out in production lets you swap approval mechanisms
(terminal → Slack → web UI) without touching skill logic.
"""

from __future__ import annotations
import json
import httpx
from .base import Skill, SkillResult


class PostReviewSkill(Skill):
    """
    Formats the review JSON into markdown, shows it for human approval,
    and posts it to GitHub if approved.

    This is a "compound skill" — it does three things internally.
    The agent sees one tool: "post the review."
    """

    def __init__(self, github_token: str, auto_approve: bool = False):
        self._token = github_token
        self._auto_approve = auto_approve  # set True in tests / CI
        self._headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @property
    def name(self) -> str:
        return "post_review"

    @property
    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "Formats the review findings, shows them to the human for approval, "
                "and posts the review to GitHub if approved. "
                "Call this once after you have completed your investigation. "
                "Pass the complete review as a JSON string."
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
                        "description": "PR number to post the review on.",
                    },
                    "review_json": {
                        "type": "string",
                        "description": (
                            "JSON string with the review. Required keys: "
                            "summary (str), verdict (approve|comment|request_changes), "
                            "findings (list), praise (str, optional)."
                        ),
                    },
                },
                "required": ["repo", "pr_number", "review_json"],
            },
        }

    def execute(self, repo: str, pr_number: int, review_json: str) -> SkillResult:
        # Step 1: Parse and validate the review JSON
        try:
            review = json.loads(review_json)
        except json.JSONDecodeError as e:
            return SkillResult.error(f"Invalid review JSON: {e}")

        required = {"summary", "verdict", "findings"}
        missing = required - set(review.keys())
        if missing:
            return SkillResult.error(f"Review JSON missing required keys: {missing}")

        # Step 2: Format into markdown
        comment_body = self._format_comment(review)

        # Step 3: Human approval gate
        approved = self._get_approval(comment_body, review["verdict"])

        if not approved:
            return SkillResult.ok(
                "Review was shown to human but not posted (declined).",
                posted=False,
                verdict=review["verdict"],
            )

        # Step 4: Post to GitHub
        return self._post_to_github(repo, pr_number, comment_body, review["verdict"])

    def _format_comment(self, review: dict) -> str:
        verdict = review.get("verdict", "comment")
        emoji = {"approve": "✅", "comment": "💬", "request_changes": "🔴"}.get(verdict, "💬")

        lines = [
            f"## {emoji} Code Review",
            "",
            f"**Summary:** {review.get('summary', '')}",
            "",
        ]

        findings = review.get("findings", [])
        if findings:
            critical   = [f for f in findings if f.get("severity") == "critical"]
            suggestion = [f for f in findings if f.get("severity") == "suggestion"]
            nits       = [f for f in findings if f.get("severity") == "nit"]

            def render(f: dict) -> list[str]:
                loc = f.get("file", "")
                if f.get("line"):
                    loc += f":{f['line']}"
                out = [f"**`{loc}`** — {f.get('issue', '')}"]
                if f.get("suggestion"):
                    out.append(f"> 💡 {f['suggestion']}")
                return out

            if critical:
                lines += ["### 🔴 Must Fix", ""]
                for f in critical:
                    lines += render(f) + [""]
            if suggestion:
                lines += ["### 💡 Suggestions", ""]
                for f in suggestion:
                    lines += render(f) + [""]
            if nits:
                lines += ["### 🔹 Nits", ""]
                for f in nits:
                    lines += render(f) + [""]
        else:
            lines += ["No issues found — looks good! 🎉", ""]

        if review.get("praise"):
            lines += [f"**👍 Well done:** {review['praise']}", ""]

        lines += ["---", "*Posted by PR review agent (Bedrock)*"]
        return "\n".join(lines)

    def _get_approval(self, comment_body: str, verdict: str) -> bool:
        """
        Human-in-the-loop gate.

        PROTOTYPE: blocks on terminal input.
        PRODUCTION: would be an async webhook / Slack button / web UI.
        The skill logic above doesn't need to change — only this method.
        """
        if self._auto_approve:
            return True

        print("\n" + "="*60)
        print(f"AGENT WANTS TO POST A REVIEW  (verdict: {verdict.upper()})")
        print("="*60)
        print(comment_body)
        print("="*60)

        while True:
            choice = input("\nPost this review? [y/n]: ").strip().lower()
            if choice in ("y", "yes"):
                print("✅ Posting...")
                return True
            elif choice in ("n", "no"):
                print("❌ Skipped.")
                return False
            print("Please enter y or n.")

    def _post_to_github(
        self, repo: str, pr_number: int, body: str, verdict: str
    ) -> SkillResult:
        """Post the review via GitHub REST API."""
        # Map verdict to GitHub event type
        event_map = {
            "approve": "APPROVE",
            "request_changes": "REQUEST_CHANGES",
            "comment": "COMMENT",
        }
        event = event_map.get(verdict, "COMMENT")

        try:
            resp = httpx.post(
                f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews",
                headers=self._headers,
                json={"body": body, "event": event},
                timeout=15,
            )
            resp.raise_for_status()
            review_url = resp.json().get("html_url", "")
            return SkillResult.ok(
                f"Review posted successfully. URL: {review_url}",
                posted=True,
                url=review_url,
                verdict=verdict,
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 422:
                return SkillResult.error(
                    "GitHub rejected the review (422). "
                    "You may not be able to review your own PR, or the PR is already merged."
                )
            return SkillResult.error(f"GitHub API error {e.response.status_code}: {e.response.text[:200]}")
        except httpx.RequestError as e:
            return SkillResult.error(f"Network error: {e}")
