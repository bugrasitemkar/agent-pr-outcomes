"""Feature extraction: author detection, blast radius, evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .codeowners import CodeOwners
from .config import CONTROL_FILES, Config
from .globs import matches_any
from .models import AuthorKind, AuthorSignal, ChangeType, Confidence, PRInput

# Known agent accounts, keyed by normalized login (lowercase, no "[bot]").
# The same bot appears differently per API: REST "devin-ai-integration[bot]",
# GraphQL "devin-ai-integration", and Copilot as REST "Copilot" / GraphQL
# "copilot-swe-agent" (verified 2026-11-10).
AGENT_LOGINS: dict[str, str] = {
    "copilot": "copilot",
    "copilot-swe-agent": "copilot",
    "devin-ai-integration": "devin",
    "cursor": "cursor",
    "cursor-agent": "cursor",
    "claude": "claude",
    "chatgpt-codex-connector": "codex",
    "openai-codex": "codex",
    "codegen-sh": "codegen",
    "sweep-ai": "sweep",
    "google-labs-jules": "jules",
}
DEPENDENCY_BOTS = {"dependabot", "renovate", "pre-commit-ci"}


def normalize_login(login: str) -> str:
    return login.strip().lower().removesuffix("[bot]")

AGENT_BRANCH_PREFIXES: dict[str, str] = {
    "copilot/": "copilot",
    "codex/": "codex",
    "cursor/": "cursor",
    "claude/": "claude",
    "devin/": "devin",
    "jules/": "jules",
}

_TRAILER = re.compile(r"^co-authored-by:\s*(?P<name>[^<\n]+)", re.IGNORECASE | re.MULTILINE)
_TRAILER_AGENTS = {
    "claude": "claude",
    "copilot": "copilot",
    "cursor": "cursor",
    "codex": "codex",
    "devin": "devin",
    "jules": "jules",
}
_BODY_MARKERS = {
    "generated with [claude code]": "claude",
    "generated with claude code": "claude",
    "created by codex": "codex",
    "devin run": "devin",
}

_CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+(?:[\w.-]+/[\w.-]+)?#\d+", re.I)
_ISSUE_URL = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/issues/\d+")
_TICKET_KEY = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d+\b")  # Linear / Jira


def detect_author(pr: PRInput, cfg: Config) -> AuthorSignal:
    login = normalize_login(pr.author_login)
    if login in DEPENDENCY_BOTS:
        return AuthorSignal(kind=AuthorKind.DEPENDENCY_BOT, confidence=Confidence.HIGH, evidence=[f"login:{login}"])

    extra = {normalize_login(x) for x in cfg.extra_agent_logins}
    if login in AGENT_LOGINS or login in extra:
        return AuthorSignal(
            kind=AuthorKind.AGENT,
            confidence=Confidence.HIGH,
            agent_name=AGENT_LOGINS.get(login, login),
            evidence=[f"login:{login}"],
        )

    evidence: list[str] = []
    agent: str | None = None
    for msg in pr.commit_messages:
        for m in _TRAILER.finditer(msg):
            name = m.group("name").strip().lower()
            for key, val in _TRAILER_AGENTS.items():
                if key in name:
                    agent = agent or val
                    evidence.append(f"trailer:{val}")
    body = pr.body.lower()
    for marker, val in _BODY_MARKERS.items():
        if marker in body:
            agent = agent or val
            evidence.append(f"body:{val}")
    for prefix, val in AGENT_BRANCH_PREFIXES.items():
        if pr.head_ref.lower().startswith(prefix):
            agent = agent or val
            evidence.append(f"branch:{val}")

    if agent:
        # Human account pushing agent-written code: signals are spoofable, so medium at most.
        conf = Confidence.MEDIUM if len(set(evidence)) >= 2 else Confidence.LOW
        return AuthorSignal(kind=AuthorKind.AGENT, confidence=conf, agent_name=agent, evidence=sorted(set(evidence)))

    if pr.author_is_bot:
        return AuthorSignal(kind=AuthorKind.OTHER_BOT, confidence=Confidence.HIGH, evidence=[f"login:{login}"])
    return AuthorSignal(kind=AuthorKind.HUMAN, confidence=Confidence.MEDIUM, evidence=["no agent signals"])


@dataclass
class BlastRadius:
    counted_lines: int = 0
    counted_files: int = 0
    control_files: list[str] = field(default_factory=list)
    critical_files: list[str] = field(default_factory=list)
    deleted_files: int = 0
    owner_sets: int = 0
    source_files: int = 0
    test_files: int = 0
    docs_only: bool = False
    truncated: bool = False
    t1_line_limit: int = 0


def blast_radius(pr: PRInput, cfg: Config) -> BlastRadius:
    br = BlastRadius()
    total = pr.changed_files_total if pr.changed_files_total is not None else len(pr.files)
    br.truncated = total > len(pr.files) or total > cfg.max_files_evaluable
    owners = CodeOwners.parse(pr.codeowners_text)

    paths = [f.path for f in pr.files]
    docs = 0
    limits: list[int] = []
    for f in pr.files:
        if f.path in CONTROL_FILES:
            br.control_files.append(f.path)
        if matches_any(cfg.critical_paths, f.path):
            br.critical_files.append(f.path)
        if f.change_type == ChangeType.REMOVED:
            br.deleted_files += 1
        is_test = matches_any(cfg.test_paths, f.path)
        is_docs = matches_any(cfg.docs_paths, f.path)
        if is_test:
            br.test_files += 1
        elif is_docs:
            docs += 1
        else:
            br.source_files += 1
        if not matches_any(cfg.size_ignore, f.path):
            br.counted_lines += f.additions + f.deletions
            br.counted_files += 1
        for pt in cfg.path_thresholds:
            if matches_any([pt.pattern], f.path):
                limits.append(pt.t1_max_lines)

    br.docs_only = bool(pr.files) and docs == len(pr.files)
    br.owner_sets = len(owners.owner_sets(paths))
    # Monorepo: the strictest matching path threshold applies.
    br.t1_line_limit = min(limits) if limits else cfg.t1_max_lines
    return br


# Tokens shaped like ticket keys that are not tickets (would wrongly unlock T1).
_NOT_TICKETS = {"UTF", "SHA", "ISO", "RFC", "CVE", "GHSA", "HTTP", "TLS", "SSL", "MD", "AES", "RSA", "ES", "PEP", "WCAG"}


def has_linked_ticket(pr: PRInput) -> bool:
    text = f"{pr.title}\n{pr.body}\n{pr.head_ref}"
    if _CLOSING.search(text) or _ISSUE_URL.search(text):
        return True
    return any(m.group(0).split("-")[0] not in _NOT_TICKETS for m in _TICKET_KEY.finditer(text))
