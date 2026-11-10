# Review Router

Risk-based review routing for agent-authored PRs. Closed source.

Plan: `~/PrimarySyncVault/personal/Projects/AI Native SDLC Fırsatları/Review Router - implementasyon planı.md`

## Layout
- `packages/engine/` — pure, I/O-free tiering engine (metadata only, no file contents)
- `apps/worker/` — FastAPI on Cloudflare Python Workers (spike pending)
- `tools/backtest/` — retrospective classification of OSS agent PRs (pending)
- `site/` — landing, docs, privacy, terms, security (pending)

## Dev
```
uv sync
uv run pytest
```
