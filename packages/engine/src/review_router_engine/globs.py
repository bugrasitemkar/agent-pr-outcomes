"""Gitignore/CODEOWNERS-style glob matching.

Rules (subset of gitignore semantics, which CODEOWNERS also uses):
- A pattern without a slash (other than a trailing one) matches at any depth.
- A leading "/" anchors the pattern to the repository root.
- A trailing "/" means "this directory and everything under it".
- "*" matches anything except "/", "?" one non-"/" character, "**" any number of path segments.
- A pattern that matches a directory also matches every file beneath it.
"""

from __future__ import annotations

import re
from functools import lru_cache


def _translate(body: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(body):
        c = body[i]
        if c == "*":
            if body[i : i + 2] == "**":
                # "**/" -> zero or more directories; trailing "**" -> anything
                if body[i : i + 3] == "**/":
                    out.append("(?:.*/)?")
                    i += 3
                    continue
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


@lru_cache(maxsize=4096)
def compile_pattern(pattern: str) -> re.Pattern[str]:
    p = pattern.strip()
    anchored = p.startswith("/")
    p = p.lstrip("/")
    dir_only = p.endswith("/")
    p = p.rstrip("/")
    if "/" in p:
        anchored = True
    body = _translate(p)
    prefix = "^" if anchored else "^(?:.*/)?"
    # Matching a directory matches everything under it; a file pattern also
    # matches a directory of that name (gitignore behaviour).
    suffix = "/.*$" if dir_only else "(?:/.*)?$"
    return re.compile(prefix + body + suffix)


def matches(pattern: str, path: str) -> bool:
    return compile_pattern(pattern).match(path.lstrip("/")) is not None


def matches_any(patterns: list[str] | tuple[str, ...], path: str) -> bool:
    return any(matches(p, path) for p in patterns)
