# Backtest pre-registration (written 2026-11-10, before any outcome data was fetched)

Purpose: kill gate from the plan. Do the engine's tiers predict real-world trouble?

## Sample
- Sources: merged PRs authored by agent apps: `copilot-swe-agent`, `devin-ai-integration`,
  `cursor`, `google-labs-jules`. Merged 2026-07-01 .. 2026-10-15 (so every PR has a full
  14-day outcome window before today).
- Search is sliced into weekly merge windows (search caps at 1,000 results per query).
- Repo filters: not a fork, not archived, ≥50 stars, ≥3 distinct human contributors,
  and CI present (non-null status rollup) on ≥50% of its sampled PRs.
- At most 30 PRs per repo (deterministic: lowest hash of PR node id).
- **Tuning / holdout split by repo**, `sha256(owner/name) % 2`, fixed before outcomes are fetched.
  0 = tuning, 1 = holdout.

## Engine inputs (must equal production)
- Author login normalized (REST/GraphQL forms differ); `author_is_bot` from GraphQL `__typename`.
- File list: GraphQL `files(first:100)`; PRs with >100 files count as truncated → T3 (known effect, also true in production v1).
- CODEOWNERS: only `.github/CODEOWNERS`, read at the PR's `baseRefOid`.
- CI state: head commit `statusCheckRollup` at time of collection (post-merge; pending is rare).
- Default `Config()`; no custom config.

## Outcomes (14 days after `mergedAt`, default-branch commits only)
- **Primary — revert**: a commit whose message contains "revert" (case-insensitive) AND
  (the PR's merge commit SHA, ≥7-char prefix, OR `Revert "<PR title>"` OR a reference to `#<PR number>`).
- **Secondary — fix follow-up**: a commit (not the revert) whose message contains a fix keyword
  (`fix`, `bug`, `hotfix`, `regression`, `broken`) AND an explicit reference to `#<PR number>`
  or the merge SHA prefix. (No file-overlap heuristic: it is confounded with file count.)
- **Combined event** = revert OR fix follow-up. The gate uses the combined event; primary is reported.

## Decision rule (holdout set only)
- Ratio R = event rate(T3) / event rate(T1). 90% CI by bootstrap over repos (2,000 resamples, seed 7).
- **Inconclusive** if holdout has <300 PRs in T1 or <300 in T3, or <30 combined events in total.
- **Pass** if R ≥ 2.0 and the CI lower bound > 1.0.
- **Fail** if R < 2.0 (with sufficient sample).
- Otherwise (R ≥ 2.0 but CI lower bound ≤ 1.0) → inconclusive.
- Inconclusive is not a kill: collect more data or extend the window, then re-run once.

## Retune rule
- Rules may be retuned **once**, using the tuning set only. The holdout is then evaluated once.
- If it fails after the single retune: stop and return to the business plan (per the implementation plan).

## Also reported (product finding, not part of the gate)
- Tier distribution. If T1 is a sliver of agent PRs, the "free senior attention" pitch is weak even if R passes.
- Per-agent breakdown and per-reason breakdown of T3.
