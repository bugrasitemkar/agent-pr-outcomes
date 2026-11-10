"""Tier decision. Fail-closed: anything uncertain lands in T2/T3, never T1.

The tier is driven by blast radius and evidence, not by who wrote the PR,
because author signals can be spoofed or missing.
"""

from __future__ import annotations

from .config import Config
from .features import blast_radius, detect_author, has_linked_ticket
from .models import AuthorKind, AuthorSignal, Confidence, Decision, PRInput, Reason, Tier


def evaluate(pr: PRInput, cfg: Config | None = None) -> Decision:
    cfg = cfg or Config()
    author = detect_author(pr, cfg)
    br = blast_radius(pr, cfg)

    t3: list[Reason] = []
    if br.control_files:
        t3.append(Reason(code="control_files", detail=f"Changes router/ownership config: {', '.join(br.control_files)}"))
    if br.truncated:
        t3.append(Reason(code="too_many_files", detail="File list too large or truncated to evaluate fully"))
    if br.critical_files:
        shown = ", ".join(br.critical_files[:5]) + (" …" if len(br.critical_files) > 5 else "")
        t3.append(Reason(code="critical_paths", detail=f"Touches critical paths: {shown}"))
    if br.counted_lines >= cfg.t3_min_lines:
        t3.append(Reason(code="large_change", detail=f"{br.counted_lines} changed lines (≥ {cfg.t3_min_lines})"))
    if br.deleted_files >= cfg.t3_min_deleted_files:
        t3.append(Reason(code="many_deletions", detail=f"{br.deleted_files} files deleted"))
    if br.owner_sets >= cfg.t3_min_owner_sets:
        t3.append(Reason(code="many_owners", detail=f"Spans {br.owner_sets} CODEOWNERS groups"))

    def decision(tier: Tier, reasons: list[Reason], missing: list[str], status: str = "final") -> Decision:
        return Decision(
            tier=tier,
            status=status,  # type: ignore[arg-type]
            author=author,
            reasons=reasons,
            missing_evidence=missing,
            counted_lines=br.counted_lines,
            counted_files=br.counted_files,
        )

    if t3:
        return decision(Tier.T3, t3, [])

    # Not high-risk. Is it small enough for the fast path?
    reasons: list[Reason] = []
    small = br.counted_lines <= br.t1_line_limit and br.counted_files <= cfg.t1_max_files
    if not small:
        reasons.append(
            Reason(code="medium_size", detail=f"{br.counted_lines} lines / {br.counted_files} files exceeds fast-path limit")
        )

    missing: list[str] = []
    if pr.ci_state == "failure":
        missing.append("CI is failing")
    elif pr.ci_state == "none":
        missing.append("No CI result found")
    if br.source_files and not br.test_files and not br.docs_only:
        missing.append("Source changes without test changes")
    if (
        author.kind == AuthorKind.AGENT
        and cfg.require_ticket_for_agent_t1
        and not has_linked_ticket(pr)
    ):
        missing.append("Agent PR without a linked issue/ticket")
    if author.kind == AuthorKind.OTHER_BOT:
        reasons.append(Reason(code="unknown_bot", detail="Authored by an unrecognised bot"))
    if author.kind == AuthorKind.AGENT and author.confidence == Confidence.LOW:
        reasons.append(Reason(code="weak_agent_signal", detail="Agent authorship inferred from a single weak signal"))

    if small and not missing and not reasons:
        if pr.ci_state == "pending":
            return decision(Tier.T1, [Reason(code="waiting_ci", detail="Eligible for fast path once CI passes")], [], "waiting_ci")
        return decision(Tier.T1, [Reason(code="fast_path", detail="Small, evidenced, outside critical paths")], [])

    if pr.ci_state == "pending" and small and not reasons:
        # CI is the only open question; wait instead of downgrading.
        rest = [m for m in missing if m != "No CI result found"]
        if not rest:
            return decision(Tier.T1, [Reason(code="waiting_ci", detail="Eligible for fast path once CI passes")], [], "waiting_ci")
    return decision(Tier.T2, reasons or [Reason(code="missing_evidence", detail="Fast path blocked by missing evidence")], missing)


def fail_closed(author_login: str, error: str) -> Decision:
    """Used by the worker when inputs could not be gathered. Never T1."""
    return Decision(
        tier=Tier.T3,
        author=AuthorSignal(kind=AuthorKind.HUMAN, confidence=Confidence.LOW, evidence=[f"unevaluated:{author_login}"]),
        reasons=[Reason(code="evaluation_error", detail=f"Could not evaluate safely: {error}")],
    )
