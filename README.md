# Merged While Red: post-merge outcomes of agent-authored pull requests

**Exploratory technical report.** It is pre-registered but not peer reviewed.
📄 Report: [`paper/whitepaper.pdf`](paper/whitepaper.pdf) · DOI: _(Zenodo, TBD)_ · Dataset: [`data/agent_pr_outcomes.csv`](data/agent_pr_outcomes.csv) · Hugging Face: _(TBD)_

We studied **2,211 merged pull requests** opened by four coding agents (GitHub Copilot coding agent, Devin, Cursor, Jules) in **571 active open-source repositories**, merged July–October 2026. Each PR got a deterministic, metadata-only risk tier. We then checked whether it was reverted, or followed by a fix that explicitly references it, within 14 days.

## Findings

- **What agent PRs look like:**
  - 52% have no linked issue.
  - 26% change source code without touching tests.
  - 16% were merged while CI was failing, pending or absent.
  - Only 7% met our fast-path criteria.
- **Trouble is rare:** 1.3% of agent PRs were followed by a revert or a referenced fix within 14 days. We audited all 29 events by hand; label precision is 62–76%.
- **The pre-registered tier test is inconclusive.** Detecting a 2× difference would need 23k–46k PRs, more than current public agent activity provides.
- **Merged while red:** PRs merged without passing CI were followed by about **3×** as much follow-up work (p = 0.003; repo-bootstrap 90% CI 1.5–6.2).
  - Part of that follow-up is build repair. Excluding it, the ratio is 2.3× (p = 0.08).
  - Under the original pre-registered label definition, the ratio is 1.5× and not significant.
  - Merging on red reliably creates follow-up work. Evidence that it causes behavioural defects is suggestive, not established.

Read the threats-to-validity section before citing any number.

## Repository layout

| Path | What |
|---|---|
| `paper/` | Report source (`whitepaper.md`), PDF, figures (`figures.py`) |
| `tools/backtest/PREREGISTRATION.md` | Pre-registration (commit `ca0a532`) and recorded deviations (frozen at `34bcb60`, before the holdout run) |
| `tools/backtest/backtest.py` | Pipeline: sample → repos → collect → history → evaluate |
| `tools/backtest/sensitivity.py` | Original-label, build-repair and audited-label sensitivity analyses |
| `tools/backtest/audit_events.csv` | Manual audit of every labelled event |
| `packages/engine/` | Deterministic, metadata-only risk-tier engine |
| `data/agent_pr_outcomes.csv` | PR-level dataset: identifiers, tier, CI state, labels. No code or PR text. |
| `apps/worker/` | Earlier product spike (Cloudflare Worker). Not used by the study. |

## Reproduce

Needs `uv` and an authenticated `gh` CLI. Collection takes several hours because of GitHub API rate limits.

```bash
uv sync
uv run pytest
uv run python tools/backtest/backtest.py sample --pages 10
uv run python tools/backtest/backtest.py repos
uv run python tools/backtest/backtest.py collect
uv run python tools/backtest/backtest.py history --max-pages 300
uv run python tools/backtest/backtest.py evaluate --split holdout
uv run python tools/backtest/backtest.py evaluate --split all
uv run python tools/backtest/sensitivity.py
uv run --with matplotlib python paper/figures.py
```

Public GitHub data changes over time: repositories get deleted, renamed or edited. Exact counts may therefore differ on re-collection.

## Citation

Sitemkar, B. (2026). *Merged While Red: Post-Merge Outcomes of 2,211 Agent-Authored Pull Requests in Open Source.* Exploratory technical report. ORCID 0009-0009-2797-7077. DOI: TBD.

## License

Code: MIT. Dataset: CC BY 4.0. It contains only public PR identifiers and derived labels.
