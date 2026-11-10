"""Engine inputs and outputs. Metadata only: no file contents or patches."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class ChangeType(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"
    RENAMED = "renamed"


class FileChange(BaseModel):
    path: str
    additions: int = 0
    deletions: int = 0
    change_type: ChangeType = ChangeType.MODIFIED


CIState = Literal["success", "failure", "pending", "none"]


class PRInput(BaseModel):
    author_login: str
    author_is_bot: bool = False
    head_ref: str = ""
    title: str = ""
    body: str = ""
    commit_messages: list[str] = Field(default_factory=list)
    files: list[FileChange] = Field(default_factory=list)
    # Total changed files reported by GitHub; may exceed len(files) when the list is truncated.
    changed_files_total: int | None = None
    ci_state: CIState = "none"
    # CODEOWNERS text read from the BASE ref (never the PR head).
    codeowners_text: str | None = None


class AuthorKind(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    DEPENDENCY_BOT = "dependency_bot"
    OTHER_BOT = "other_bot"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AuthorSignal(BaseModel):
    kind: AuthorKind
    confidence: Confidence
    agent_name: str | None = None
    evidence: list[str] = Field(default_factory=list)


class Tier(StrEnum):
    T1 = "T1"  # fast path
    T2 = "T2"  # single reviewer
    T3 = "T3"  # senior / owner required


class Reason(BaseModel):
    code: str
    detail: str


class Decision(BaseModel):
    tier: Tier
    # "waiting_ci" means the check should stay in_progress until CI finishes.
    status: Literal["final", "waiting_ci"] = "final"
    author: AuthorSignal
    reasons: list[Reason] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    counted_lines: int = 0
    counted_files: int = 0
