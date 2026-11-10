"""Sensitivity analyses for the CI finding (paper section 5.3, Appendix B).

1. Original (pre-registered, uncorrected) label definition from commit ca0a532.
2. Excluding build-repair follow-ups (tests/lint/CI/e2e) to check circularity.
3. Audited labels only (audit_events.csv).

Run after `backtest.py evaluate --split all`:
    uv run python tools/backtest/sensitivity.py
"""

import csv
import datetime as dt
import importlib.util
import json
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import backtest as bt  # noqa: E402

BUILD = re.compile(r"\b(test|tests|lint|clippy|ci|e2e|flak\w*|format\w*|appium|assertion|typecheck|build)\b", re.I)

rows = [json.loads(line) for line in (bt.DATA / "rows_all.jsonl").read_text().splitlines()]
prs = {(p["repo"], p["number"]): p for p in bt.read_jsonl(bt.DATA / "prs.jsonl")}
audit = {(r["repo"], int(r["number"])): r["verdict"] for r in csv.DictReader(open(HERE / "audit_events.csv"))}
_hist: dict[str, list] = {}


def history(repo):
    if repo not in _hist:
        _hist[repo] = bt.read_jsonl(bt.hist_path(repo))
    return _hist[repo]


def event_subject(r):
    p = prs[(r["repo"], r["number"])]
    merged = dt.datetime.fromisoformat(p["mergedAt"].replace("Z", "+00:00"))
    end = merged + dt.timedelta(days=bt.WINDOW_DAYS)
    sha = ((p.get("mergeCommit") or {}).get("oid") or "")[:7]
    for c in history(r["repo"]):
        w = dt.datetime.fromisoformat(c["committedDate"].replace("Z", "+00:00"))
        if merged < w <= end and not c["oid"].startswith(sha) and bt.outcomes(p, [c])["event"]:
            return c["message"].splitlines()[0]
    return ""


def compare(name, ev, subset=rows):
    y = [r for r in subset if r["ci"] != "success"]
    n = [r for r in subset if r["ci"] == "success"]
    a, c = sum(map(ev, y)), sum(map(ev, n))
    p = bt.fisher_two_sided(a, len(y) - a, c, len(n) - c)
    by: dict[str, list] = {}
    for r in subset:
        by.setdefault(r["repo"], []).append(r)
    repos, rng, boots = list(by), random.Random(7), []
    for _ in range(2000):
        s = [x for _ in repos for x in by[rng.choice(repos)]]
        yy = [r for r in s if r["ci"] != "success"]
        nn = [r for r in s if r["ci"] == "success"]
        cn = sum(map(ev, nn))
        if yy and cn:
            boots.append((sum(map(ev, yy)) / len(yy)) / (cn / len(nn)))
    boots.sort()
    rr = (a / len(y)) / (c / len(n)) if c else float("inf")
    print(f"{name:48} {a}/{len(y)} vs {c}/{len(n)}  RR={rr:.2f}  p={p:.4f}  "
          f"boot90=[{boots[int(.05 * len(boots))]:.2f}, {boots[int(.95 * len(boots)) - 1]:.2f}]")


# 1. original label definition
src = subprocess.run(["git", "show", "ca0a532:tools/backtest/backtest.py"], capture_output=True, text=True,
                     check=True, cwd=HERE).stdout
with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
    f.write(src)
spec = importlib.util.spec_from_file_location("bt_orig", f.name)
orig = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orig)
for r in rows:
    r["ev_orig"] = orig.outcomes(prs[(r["repo"], r["number"])], history(r["repo"]))["event"]
    r["build_repair"] = bool(r["event"] and not r["revert"] and BUILD.search(event_subject(r)))

print(f"events: corrected={sum(r['event'] for r in rows)}  original={sum(r['ev_orig'] for r in rows)}  "
      f"build-repair={sum(r['build_repair'] for r in rows)}\n")
compare("corrected labels (reported)", lambda r: r["event"])
for split in ("tuning", "holdout"):
    compare(f"  corrected, {split}", lambda r: r["event"], [r for r in rows if r["split"] == split])
compare("original pre-registered labels", lambda r: r["ev_orig"])
compare("  original, holdout", lambda r: r["ev_orig"], [r for r in rows if r["split"] == "holdout"])
compare("excluding build-repair follow-ups", lambda r: r["event"] and not r["build_repair"])
compare("audited true only", lambda r: r["event"] and audit.get((r["repo"], r["number"])) == "true")
compare("reverts only", lambda r: r["revert"])
