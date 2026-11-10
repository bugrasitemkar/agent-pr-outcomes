---
title: "What Predicts Trouble in Agent-Authored Pull Requests? A Pre-Registered Exploratory Study of Four Coding Agents in Open Source"
author: "Bugra Sitemkar (independent researcher, ORCID 0009-0009-2797-7077)"
date: "DRAFT — 2026-11"
status: "Exploratory technical report. Not peer reviewed."
---

<!-- DRAFT. Sections marked [RESULTS] are filled after the backtest completes. -->

## Abstract

[RESULTS] One paragraph: motivation (agents now open a large share of PRs, review is the bottleneck, platforms ship AI approval without publishing outcome data); data (N merged PRs from 4 coding agents across M open-source repositories, Jul–Oct 2026); method (pre-registered, deterministic metadata-only risk tiers; outcome = revert or explicitly-referenced fix within 14 days); headline finding with effect size, 90% CI and p-value; main limitation; link to code, data and pre-registration.

## 1. Introduction

Coding agents moved from autocomplete to authorship in 2025–2026. GitHub reports that agents initiated more than 40% of pull requests on the platform by September 2026, up from 17% in March of the same year [Octoverse 2026]. Downstream processes — review, CI, release — now scale with PR volume rather than headcount, and several telemetry studies report that review time and post-merge incidents rose alongside AI adoption [Faros 2025, 2026; DORA 2025].

Platforms have responded by letting AI approve changes. Copilot code review gained the ability to approve pull requests (general availability on 2026-10-28) with path-level restrictions [GitHub changelog]; Cursor routes PRs by risk and auto-approves those below a configurable threshold [Cursor docs]; CodeRabbit merges "low-risk" changes by rule [CodeRabbit]. Large engineering organisations report building the same pattern in-house [Vercel; Meta RADAR]. What is largely missing from public view is **outcome data**: which properties of an agent-authored change predict that it will later be reverted or need a fix?

This report asks a narrow, measurable question:

> Among merged pull requests authored by coding agents in open-source repositories, do simple, explainable, metadata-only risk signals predict post-merge trouble (revert or explicitly-referenced fix within 14 days)?

We deliberately use signals that can be computed **without reading code content** — file paths, change size, ownership boundaries, CI state, presence of tests and linked tickets — because these are cheap, deterministic, auditable, and privacy-preserving. The study was **pre-registered**: metrics, thresholds and decision rules were committed to a public repository before any outcome data was fetched.

Contributions:
1. A pre-registered, reproducible pipeline for measuring post-merge outcomes of agent-authored PRs from public GitHub data.
2. An exploratory analysis of which metadata signals are associated with reverts and fixes across four coding agents.
3. An open dataset of PR identifiers, features, tiers and outcome labels (no code or PR text).

## 2. Background and related work

**Productivity and quality of AI-assisted development.** Evidence is mixed. Telemetry from Faros AI across >10,000 developers associates high AI adoption with more merged PRs but also longer review times and larger PRs, without a clear company-level delivery improvement [Faros 2025]; its 2026 follow-up reports large increases in review time and incidents per PR [Faros 2026]. DORA 2025 concludes that AI amplifies existing engineering conditions rather than automatically improving delivery [DORA 2025]. METR's randomised study found experienced developers were slower with early-2025 tools despite believing otherwise, with a 2026 update reporting a small, uncertain speed-up [METR 2025, 2026]. Vendor studies report more issues in AI-authored PRs [CodeRabbit 2025] and frequent security weaknesses in LLM-generated code [Veracode 2025]. These are primarily productivity or code-level quality measures; few report **post-merge outcomes by change type for agent-authored PRs**.

**Risk-based review.** The idea that review effort should be proportional to change risk predates coding agents (e.g. ownership-aware review routing, CODEOWNERS). Practitioner reports describe risk-based review increasing merge throughput [Pragmatic Engineer 2026], and industrial systems combine static heuristics with learned risk scores [Meta RADAR, arXiv 2605.30208]. Commercial tools now ship AI approval and risk routing (Section 1), but we found no published false-approval or post-merge revert rates for these systems.

**Measuring defect-inducing changes.** Post-merge outcomes are usually approximated with SZZ-style heuristics that link fixing commits to the changes that introduced the defect. These heuristics are noisy; reported precision varies widely [Rosa et al. 2021; SANER 2025]. We therefore use a deliberately conservative outcome definition (explicit reverts and fixes that reference the PR) and report it as a lower bound rather than a defect rate.

## 3. Data

**Sources.** Merged pull requests authored by four coding-agent GitHub Apps — `copilot-swe-agent`, `devin-ai-integration`, `cursor`, `google-labs-jules` — merged between 2026-07-01 and 2026-10-15, so that every PR has a complete 14-day outcome window before data collection. GitHub search was sliced into weekly windows to stay within its 1,000-results-per-query cap.

**Repository filters (pre-registered).** Not a fork; not archived; ≥ 50 stars; ≥ 3 distinct human contributors; and CI results present on ≥ 50% of sampled PRs. These filters remove personal and toy repositories, which dominate raw agent PR volume. At most 30 PRs per repository were sampled (deterministic hash order) so that no single project dominates.

**Funnel.** [RESULTS] 61,629 candidate PRs in 12,331 repositories → 630 repositories passing star/fork/contributor filters → 2,361 PRs collected → N after CI-coverage filter. Per-agent counts.

**Features (metadata only).** For each PR: author account type and identity; file paths with additions, deletions and change type (GitHub GraphQL, which exposes no patch content); total changed files; head-commit CI rollup state; commit messages (for agent trailers); title, body and branch name (for ticket references only); and `.github/CODEOWNERS` read at the PR's base commit.

**Split.** Repositories were assigned to a tuning or holdout set by `sha256(owner/name) mod 2` before outcomes were fetched.

## 4. Method

**Risk tiers.** A deterministic rules engine (released with this report) assigns each PR to one of three tiers:
- **T3 (owner/senior review)** if any of: touches review-control files (CODEOWNERS, router config); file list truncated or > 3,000 files; touches critical paths (migrations, infrastructure, CI workflows, auth/security, dependency manifests); ≥ 800 counted changed lines (lockfiles and generated files excluded); ≥ 10 deleted files; spans ≥ 3 CODEOWNERS groups.
- **T1 (fast path)** if small (≤ 150 counted lines, ≤ 10 files), CI passing, tests changed alongside source (or docs-only), and — for agent PRs — a linked issue or ticket.
- **T2** otherwise. Ambiguity resolves upward (fail-closed): uncertain inputs never yield T1.

Tiers depend on the change's blast radius and evidence, not on which agent wrote it.

**Outcomes (14 days after merge, default-branch commits).**
- *Revert*: a commit containing "revert" and the PR's merge SHA (≥ 7 chars), the PR number, or `Revert "<PR title>"`.
- *Fix follow-up*: a non-revert commit with a fix keyword (`fix`, `bug`, `hotfix`, `regression`, `broken`) that explicitly references the PR number or merge SHA.
- *Event* = revert OR fix follow-up.

**Pre-registered decision rule (holdout).** Ratio R = event rate(T3) / event rate(T1) with a 90% bootstrap CI over repositories (2,000 resamples). Pass if R ≥ 2 and CI lower bound > 1; fail if R < 2; inconclusive if T1 or T3 has < 300 PRs or there are < 30 events.

**Exploratory analysis.** For each binary feature, event rates with vs. without the feature, two-sided Fisher exact test, Holm–Bonferroni correction across features. Findings are described as significant only when the Holm-adjusted p < 0.05; all others are reported as trends.

## 5. Results

[RESULTS]
5.1 Sample and tier distribution (table; per agent).
5.2 Pre-registered test: R, 90% CI, Fisher p, verdict.
5.3 Exploratory feature associations (table: n with/without, rates, rate ratio, p, Holm p).
5.4 Per-agent outcome rates (descriptive only; not a vendor ranking — see threats).

## 6. Threats to validity

- **Outcome measurement.** Reverts and explicitly-referenced fixes are a lower bound on trouble; silent fixes, direct pushes without references, and incidents not tracked in git are missed. Label noise is expected despite the conservative definition.
- **Selection.** Open-source repositories with ≥ 50 stars are not representative of private enterprise codebases. Agents may be deployed on easier tasks; maintainers may merge agent PRs selectively.
- **Confounding.** Larger or critical-path changes may be reverted more because they are more visible or because the projects that make them are more active, not only because they are riskier. Per-agent differences are confounded with repository mix and task type; we do not rank vendors.
- **Clustering.** PRs within a repository are not independent; we bootstrap by repository for the primary ratio but Fisher tests in the exploratory table treat PRs as independent.
- **Attribution.** Agent identity comes from the PR author account; human-pushed agent code is not captured.
- **Point in time.** Agents and platforms changed rapidly during the study window.
- **Researcher degrees of freedom.** Mitigated by pre-registration (commit hash in Appendix) and a single tuning/holdout split; any deviation is listed in Appendix B.

## 7. Practical implications

[RESULTS] Which agent PRs should always get human review; what to require before auto-approval (CI, tests, ticket links); how teams can replicate the measurement on their own repositories.

## 8. Reproducibility

Code (MIT), pre-registration, and the PR-level dataset (identifiers, features, tiers, outcome labels; no code or PR text) are available at:
- GitHub: `github.com/bugrasitemkar/agent-pr-outcomes` [TBD]
- Hugging Face dataset: [TBD]
- Zenodo DOI: [TBD] (primary citable version; arXiv not planned)

## Appendix A — Pre-registration

Committed in `tools/backtest/PREREGISTRATION.md` at commit `ca0a532` (2026-11-10), before outcome data was fetched.

## Appendix B — Deviations from pre-registration

- Statistical reporting extended with Fisher exact tests and Holm correction (exploratory, added before outcomes were evaluated).
- [Any sample extension will be listed here.]

## References (to be completed and verified)

- [Octoverse 2026] GitHub. Octoverse 2026.
- [Faros 2025] Faros AI. The AI Productivity Paradox Report.
- [Faros 2026] Faros AI. AI Acceleration Whiplash.
- [DORA 2025] Google Cloud. State of AI-assisted Software Development.
- [METR 2025, 2026] METR. Developer productivity RCT and 2026 uplift update.
- [CodeRabbit 2025] CodeRabbit. State of AI vs Human Code Generation.
- [Veracode 2025] Veracode. GenAI code security report.
- [GitHub changelog] Copilot code review approvals, 2026-09-01 and 2026-10-28.
- [Cursor docs] PR Routing & Approval.
- [CodeRabbit] Agentic Change Management, 2026-08-12.
- [Vercel] 58% of PRs in our largest monorepo merge without human review.
- [Meta RADAR] arXiv:2605.30208.
- [Pragmatic Engineer 2026] What is happening with code reviews?
- [Rosa et al. 2021] Evaluating SZZ implementations. arXiv:2102.03300.
- [SANER 2025] Corner cases in bug-inducing commits.
