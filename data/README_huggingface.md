---
license: cc-by-4.0
pretty_name: Agent PR Outcomes (Merged While Red)
language:
- en
tags:
- software-engineering
- coding-agents
- pull-requests
- code-review
size_categories:
- 1K<n<10K
task_categories:
- tabular-classification
---

# Agent PR Outcomes

This dataset has 2,211 merged pull requests opened by four coding agents: GitHub Copilot coding agent, Devin, Cursor and Jules. They come from 571 active open-source repositories (≥50 stars, ≥3 human contributors) and were merged between 2026-07-01 and 2026-10-15. Each PR has a deterministic, metadata-only risk tier, its CI state at merge, and 14-day post-merge outcome labels.

It accompanies the exploratory technical report *Merged While Red* (Sitemkar, 2026). The code, the pre-registration and the full methodology are at https://github.com/bugrasitemkar/agent-pr-outcomes.

## Columns

| Column | Description |
|---|---|
| `repo`, `pr_number`, `pr_url` | Public PR identifier |
| `agent` | Authoring GitHub App: `copilot-swe-agent`, `devin-ai-integration`, `cursor` or `google-labs-jules` |
| `split` | `tuning` / `holdout`, assigned by repository hash before outcomes were fetched |
| `tier` | T1 = fast path, T2 = single reviewer, T3 = owner/senior review (rules in the report, §4) |
| `ci_state_at_merge` | Head-commit status rollup: `success`, `failure`, `pending` or `none` |
| `t3_reasons` | Why the PR was T3, for example `critical_paths` or `large_change` |
| `missing_evidence` | What kept the PR out of T1 |
| `reverted_14d`, `fix_followup_14d`, `event_14d` | Outcome labels (0/1). Lower bounds; precision 62–76% by manual audit |
| `audit_verdict` | For labelled events: `true`, `probable`, `ambiguous` or `false` |

## Limitations

- Labels are approximate lower bounds. Silent fixes and incidents that happen outside git are not captured.
- Public open-source repositories are not representative of private codebases.
- Per-agent differences are confounded by repository and task mix. Do not use this dataset to rank vendors.
- The dataset contains no code, PR text or author identities beyond the agent app.

## Citation

Sitemkar, B. (2026). *Merged While Red: Post-Merge Outcomes of 2,211 Agent-Authored Pull Requests in Open Source.* DOI: TBD.
