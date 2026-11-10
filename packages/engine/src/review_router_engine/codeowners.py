"""CODEOWNERS parsing. The last matching rule wins, as GitHub documents."""

from __future__ import annotations

from dataclasses import dataclass

from .globs import matches

# GitHub looks for CODEOWNERS in these locations, in this order.
CODEOWNERS_LOCATIONS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")

# The only path the App reads (single-file permission covers exactly one path;
# decided 2026-11-10). Repos with CODEOWNERS elsewhere get default rules.
# All three locations remain control files: touching any of them forces T3.
CODEOWNERS_READ_PATH = ".github/CODEOWNERS"


@dataclass(frozen=True)
class Rule:
    pattern: str
    owners: tuple[str, ...]


class CodeOwners:
    def __init__(self, rules: list[Rule]):
        self.rules = rules

    @classmethod
    def parse(cls, text: str | None) -> "CodeOwners":
        rules: list[Rule] = []
        for raw in (text or "").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            # Inline comments start at " #"; a pattern may begin with an escaped "\#".
            line = line.split(" #", 1)[0].strip()
            parts = line.split()
            # A pattern with no owners is valid: it removes ownership for matching paths.
            rules.append(Rule(pattern=parts[0], owners=tuple(parts[1:])))
        return cls(rules)

    def owners_for(self, path: str) -> tuple[str, ...]:
        found: tuple[str, ...] = ()
        for rule in self.rules:
            if matches(rule.pattern, path):
                found = rule.owners  # last match wins
        return found

    def owner_sets(self, paths: list[str]) -> set[tuple[str, ...]]:
        return {o for p in paths if (o := self.owners_for(p))}
