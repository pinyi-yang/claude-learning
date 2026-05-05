"""
skills/base.py — the Skill base class.

WHY A BASE CLASS?
-----------------
Every skill needs the same three things:
  1. A JSON schema (so the agent can call it)
  2. An execute() method (the actual implementation)
  3. A name (to route tool_use blocks back to the right skill)

The base class enforces this contract. Any class that forgets to
implement `schema` or `execute` will raise NotImplementedError at
import time — not silently at runtime.

MENTAL MODEL:
------------
Think of a Skill as a "capability card" you hand to the agent.
The schema is the front of the card (what it can do, what it needs).
The execute() is the back (how it actually does it).

The agent sees only the front. Your code handles the back.

COMPOSABILITY:
-------------
Skills can call other skills internally. A `full_pr_review` skill
could call `fetch_pr_context` and `fetch_existing_comments` as
sub-steps, then return the combined result. The agent still sees
one tool. You get reusable building blocks.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SkillResult:
    """
    Structured return type from skill execution.

    Always return a SkillResult, never a raw string.
    This lets callers check success/failure before feeding
    the content back to the model.
    """
    content: str        # what gets fed back to the model as tool_result
    success: bool       # did the skill complete successfully?
    metadata: dict      # anything useful for logging/tracing (not sent to model)

    @classmethod
    def ok(cls, content: str, **metadata) -> "SkillResult":
        return cls(content=content, success=True, metadata=metadata)

    @classmethod
    def error(cls, message: str, **metadata) -> "SkillResult":
        # Return error as content — model can reason about it and recover
        # NEVER raise from here — that would crash the agent loop
        return cls(content=f"Error: {message}", success=False, metadata=metadata)


class Skill(ABC):
    """
    Base class for all agent skills.

    Subclasses must implement:
      - name (str property) — must match the tool name in schema
      - schema (dict property) — JSON schema for the Anthropic API
      - execute(**kwargs) -> SkillResult — the actual implementation
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name — must exactly match schema['name']."""
        ...

    @property
    @abstractmethod
    def schema(self) -> dict:
        """
        Full tool schema dict for the Anthropic API tools= parameter.
        Must include: name, description, input_schema.
        """
        ...

    @abstractmethod
    def execute(self, **kwargs) -> SkillResult:
        """
        Execute the skill with provided arguments.

        kwargs come directly from the model's tool_use block input.
        Always return a SkillResult — never raise.
        """
        ...

    def __init_subclass__(cls, **kwargs):
        """Validate subclass at definition time, not at runtime."""
        super().__init_subclass__(**kwargs)
        # We can't check abstractmethods here easily, but the ABC
        # mechanism handles it — instantiating an incomplete subclass
        # raises TypeError immediately.


class SkillRegistry:
    """
    Registry that maps tool names to Skill instances.

    Usage:
        registry = SkillRegistry()
        registry.register(FetchPRContextSkill(token))
        registry.register(PostReviewSkill(token))

        # Get all schemas for the API call
        tools = registry.schemas

        # Execute a tool_use block
        result = registry.execute("fetch_pr_context", {"repo": "...", "pr_number": 1})
    """

    def __init__(self):
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> "SkillRegistry":
        """Register a skill. Returns self for chaining."""
        if skill.name in self._skills:
            raise ValueError(f"Skill '{skill.name}' already registered.")
        self._skills[skill.name] = skill
        return self

    @property
    def schemas(self) -> list[dict]:
        """All tool schemas — pass this to the API tools= parameter."""
        return [skill.schema for skill in self._skills.values()]

    def execute(self, tool_name: str, tool_input: dict) -> SkillResult:
        """Route a tool_use block to the right skill."""
        skill = self._skills.get(tool_name)
        if skill is None:
            return SkillResult.error(
                f"Unknown tool '{tool_name}'. Available: {list(self._skills.keys())}"
            )
        try:
            return skill.execute(**tool_input)
        except TypeError as e:
            # Wrong arguments — likely a schema mismatch
            return SkillResult.error(f"Bad arguments for '{tool_name}': {e}")
        except Exception as e:
            # Catch-all — skills should never let this happen, but we protect the loop
            return SkillResult.error(f"Unexpected error in '{tool_name}': {type(e).__name__}: {e}")

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, name: str) -> bool:
        return name in self._skills