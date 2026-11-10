"""Retrospective backtest of the Review Router engine on public agent PRs.

Pipeline (each step caches to tools/backtest/data/ and resumes):
  sample    search merged agent PRs in weekly windows        -> candidates.jsonl
  repos     fetch repo metadata, apply repo filters          -> repos.jsonl
  collect   fetch PR details + CODEOWNERS at base            -> prs.jsonl
  history   default-branch commits per repo (outcome window) -> history/*.jsonl
  evaluate  run engine offline, label outcomes, report       -> stdout + report.json

See PREREGISTRATION.md for the fixed metrics and decision rule.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from review_router_engine import ChangeType, Config, FileChange, PRInput, Tier, evaluate

DATA = Path(__file__).parent / "data"
SOURCES = ["copilot-swe-agent", "devin-ai-integration", "cursor", "google-labs-jules"]
START, END = dt.date(2026, 7, 1), dt.date(2026, 10, 15)
WINDOW_DAYS = 14
MAX_PER_REPO = 30
MIN_STARS = 50
MIN_HUMANS = 3

_TOKEN: str | None = None


def token() -> str:
    global _TOKEN
    if _TOKEN is None:
        _TOKEN = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
    return _TOKEN


def http(method: str, url: str, body: dict | None = None) -> tuple[int, dict | list | None, dict]:
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(8):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {token()}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "review-router-backtest")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read() or b"null"), dict(r.headers)
        except urllib.error.HTTPError as e:
            hdrs = dict(e.headers)
            if e.code in (403, 429, 502, 503, 504):
                wait = int(hdrs.get("Retry-After") or 0)
                if not wait and hdrs.get("X-RateLimit-Remaining") == "0":
                    wait = max(1, int(hdrs.get("X-RateLimit-Reset", time.time() + 60)) - int(time.time()) + 2)
                wait = wait or min(60, 5 * 2**attempt)
                print(f"  http {e.code}, sleeping {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            try:
                payload = json.loads(e.read() or b"null")
            except Exception:
                payload = None
            return e.code, payload, hdrs
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"  network error {e}, retrying", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"giving up on {url}")


def gql(query: str, variables: dict | None = None) -> dict:
    status, payload, _ = http("POST", "https://api.github.com/graphql", {"query": query, "variables": variables or {}})
    if status != 200 or payload is None:
        raise RuntimeError(f"graphql {status}: {payload}")
    if payload.get("errors") and not payload.get("data"):
        raise RuntimeError(f"graphql errors: {payload['errors'][:2]}")
    return payload.get("data") or {}


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def h(s: str) -> int:
    return int(hashlib.sha256(s.encode()).hexdigest(), 16)


def split_of(repo: str) -> str:
    return "holdout" if h(repo) % 2 else "tuning"


# --------------------------------------------------------------------------- sample


def cmd_sample(args) -> None:
    out = DATA / "candidates.jsonl"
    done = {(r["source"], r["window"]) for r in read_jsonl(DATA / "sample_windows.jsonl")}
    day = START
    while day <= END:
        end = min(day + dt.timedelta(days=6), END)
        window = f"{day}..{end}"
        for src in SOURCES:
            if (src, window) in done:
                continue
            rows = []
            for page in range(1, args.pages + 1):
                q = f"is:pr is:merged is:public author:app/{src} merged:{window}"
                url = "https://api.github.com/search/issues?" + urllib.parse.urlencode(
                    {"q": q, "per_page": 100, "page": page, "sort": "created"}
                )
                status, payload, _ = http("GET", url)
                time.sleep(2.2)  # search: 30 req/min
                items = (payload or {}).get("items", []) if status == 200 else []
                for it in items:
                    repo = it["repository_url"].split("/repos/")[1]
                    rows.append({"repo": repo, "number": it["number"], "source": src})
                if len(items) < 100:
                    break
            append_jsonl(out, rows)
            append_jsonl(DATA / "sample_windows.jsonl", [{"source": src, "window": window, "n": len(rows)}])
            print(f"{window} {src}: {len(rows)}")
        day = end + dt.timedelta(days=1)


# --------------------------------------------------------------------------- repos

REPO_Q = """
fragment R on Repository { nameWithOwner stargazerCount isFork isArchived defaultBranchRef { name } }
query { %s }
"""


def cmd_repos(args) -> None:
    cands = read_jsonl(DATA / "candidates.jsonl")
    counts = Counter(c["repo"] for c in cands)
    have = {r["repo"] for r in read_jsonl(DATA / "repos.jsonl")}
    todo = [r for r in counts if r not in have]
    print(f"{len(counts)} repos, {len(todo)} to fetch")
    for i in range(0, len(todo), 40):
        chunk = todo[i : i + 40]
        parts = []
        for j, repo in enumerate(chunk):
            o, n = repo.split("/", 1)
            parts.append(f'r{j}: repository(owner: {json.dumps(o)}, name: {json.dumps(n)}) {{ ...R }}')
        try:
            data = gql(REPO_Q % "\n".join(parts))
        except RuntimeError as e:
            print("  repo batch failed:", e, file=sys.stderr)
            data = {}
        rows = []
        for j, repo in enumerate(chunk):
            d = data.get(f"r{j}")
            if not d:
                rows.append({"repo": repo, "missing": True})
                continue
            rows.append(
                {
                    "repo": repo,
                    "stars": d["stargazerCount"],
                    "fork": d["isFork"],
                    "archived": d["isArchived"],
                    "default_branch": (d.get("defaultBranchRef") or {}).get("name"),
                }
            )
        # human contributor count only for repos passing the cheap filters
        for row in rows:
            if row.get("missing") or row["fork"] or row["archived"] or row["stars"] < MIN_STARS:
                continue
            status, payload, _ = http("GET", f"https://api.github.com/repos/{row['repo']}/contributors?per_page=30")
            humans = [c for c in (payload or []) if isinstance(c, dict) and c.get("type") == "User"]
            row["humans"] = len(humans)
        append_jsonl(DATA / "repos.jsonl", rows)
        print(f"  repos {i + len(chunk)}/{len(todo)}")


def eligible_repos() -> dict[str, dict]:
    out = {}
    for r in read_jsonl(DATA / "repos.jsonl"):
        if r.get("missing") or r["fork"] or r["archived"] or r["stars"] < MIN_STARS:
            continue
        if r.get("humans", 0) < MIN_HUMANS:
            continue
        out[r["repo"]] = r
    return out


# --------------------------------------------------------------------------- collect

PR_FIELDS = """
fragment P on PullRequest {
  id number title body headRefName baseRefOid mergedAt changedFiles
  mergeCommit { oid }
  author { login __typename }
  files(first: 100) { nodes { path additions deletions changeType } }
  commits(first: 50) { nodes { commit { message } } }
  last: commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
}
"""


def cmd_collect(args) -> None:
    repos = eligible_repos()
    cands = [c for c in read_jsonl(DATA / "candidates.jsonl") if c["repo"] in repos]
    # dedupe + cap per repo deterministically
    seen, by_repo = set(), defaultdict(list)
    for c in cands:
        key = (c["repo"], c["number"])
        if key not in seen:
            seen.add(key)
            by_repo[c["repo"]].append(c)
    picked = []
    for repo, rows in by_repo.items():
        rows.sort(key=lambda c: h(f"{repo}#{c['number']}"))
        picked.extend(rows[:MAX_PER_REPO])
    have = {(p["repo"], p["number"]) for p in read_jsonl(DATA / "prs.jsonl")}
    todo = [c for c in picked if (c["repo"], c["number"]) not in have]
    print(f"{len(repos)} eligible repos, {len(picked)} PRs picked, {len(todo)} to fetch")
    for i in range(0, len(todo), 10):
        chunk = todo[i : i + 10]
        parts = []
        for j, c in enumerate(chunk):
            o, n = c["repo"].split("/", 1)
            parts.append(
                f'p{j}: repository(owner: {json.dumps(o)}, name: {json.dumps(n)}) '
                f'{{ pullRequest(number: {c["number"]}) {{ ...P }} }}'
            )
        try:
            data = gql(PR_FIELDS + "query { " + "\n".join(parts) + " }")
        except RuntimeError as e:
            print("  pr batch failed:", e, file=sys.stderr)
            continue
        # CODEOWNERS at each PR's base commit (second query, needs baseRefOid)
        prs = []
        for j, c in enumerate(chunk):
            pr = ((data.get(f"p{j}") or {}).get("pullRequest")) or None
            if pr:
                prs.append((c, pr))
        if prs:
            parts = []
            for j, (c, pr) in enumerate(prs):
                o, n = c["repo"].split("/", 1)
                expr = json.dumps(f'{pr["baseRefOid"]}:.github/CODEOWNERS')
                parts.append(
                    f'c{j}: repository(owner: {json.dumps(o)}, name: {json.dumps(n)}) '
                    f'{{ object(expression: {expr}) {{ ... on Blob {{ text }} }} }}'
                )
            try:
                co = gql("query { " + "\n".join(parts) + " }")
            except RuntimeError:
                co = {}
            rows = []
            for j, (c, pr) in enumerate(prs):
                obj = ((co.get(f"c{j}") or {}).get("object")) or {}
                rows.append({"repo": c["repo"], "source": c["source"], **pr, "codeowners": obj.get("text")})
            append_jsonl(DATA / "prs.jsonl", rows)
        print(f"  prs {i + len(chunk)}/{len(todo)}")


# --------------------------------------------------------------------------- history

HIST_Q = """
query($o: String!, $n: String!, $since: GitTimestamp!, $until: GitTimestamp!, $after: String) {
  repository(owner: $o, name: $n) { defaultBranchRef { target { ... on Commit {
    history(first: 100, since: $since, until: $until, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes { oid committedDate message }
  } } } } }
}
"""


def hist_path(repo: str) -> Path:
    return DATA / "history" / (repo.replace("/", "__") + ".jsonl")


def cmd_history(args) -> None:
    prs = read_jsonl(DATA / "prs.jsonl")
    span: dict[str, list[str]] = defaultdict(list)
    for p in prs:
        if p.get("mergedAt"):
            span[p["repo"]].append(p["mergedAt"])
    todo = [r for r in span if not hist_path(r).exists()]
    print(f"{len(span)} repos, {len(todo)} to fetch")
    for k, repo in enumerate(todo):
        since = min(span[repo])
        until_dt = dt.datetime.fromisoformat(max(span[repo]).replace("Z", "+00:00")) + dt.timedelta(days=WINDOW_DAYS)
        until = until_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        o, n = repo.split("/", 1)
        after, rows, pages = None, [], 0
        while True:
            try:
                d = gql(HIST_Q, {"o": o, "n": n, "since": since, "until": until, "after": after})
            except RuntimeError as e:
                print("  history failed:", repo, e, file=sys.stderr)
                break
            hist = (((d.get("repository") or {}).get("defaultBranchRef") or {}).get("target") or {}).get("history")
            if not hist:
                break
            rows.extend(hist["nodes"])
            pages += 1
            if not hist["pageInfo"]["hasNextPage"] or pages >= args.max_pages:
                break
            after = hist["pageInfo"]["endCursor"]
        hist_path(repo).parent.mkdir(parents=True, exist_ok=True)
        hist_path(repo).write_text("".join(json.dumps(r) + "\n" for r in rows))
        print(f"  history {k + 1}/{len(todo)} {repo}: {len(rows)} commits")


# --------------------------------------------------------------------------- evaluate

FIX_KW = re.compile(r"\b(fix(e[sd])?|bug|hotfix|regression|broken)\b", re.I)


def to_input(p: dict) -> PRInput:
    rollup = (((p.get("last") or {}).get("nodes") or [{}])[0].get("commit") or {}).get("statusCheckRollup")
    state = (rollup or {}).get("state")
    ci = {"SUCCESS": "success", "FAILURE": "failure", "ERROR": "failure", "PENDING": "pending", "EXPECTED": "pending"}.get(
        state or "", "none"
    )
    author = p.get("author") or {}
    files = [
        FileChange(
            path=f["path"],
            additions=f["additions"],
            deletions=f["deletions"],
            change_type={
                "ADDED": ChangeType.ADDED,
                "DELETED": ChangeType.REMOVED,
                "RENAMED": ChangeType.RENAMED,
            }.get(f["changeType"], ChangeType.MODIFIED),
        )
        for f in ((p.get("files") or {}).get("nodes") or [])
    ]
    return PRInput(
        author_login=author.get("login") or "ghost",
        author_is_bot=author.get("__typename") == "Bot",
        head_ref=p.get("headRefName") or "",
        title=p.get("title") or "",
        body=p.get("body") or "",
        commit_messages=[n["commit"]["message"] for n in ((p.get("commits") or {}).get("nodes") or [])],
        files=files,
        changed_files_total=p.get("changedFiles"),
        ci_state=ci,  # type: ignore[arg-type]
        codeowners_text=p.get("codeowners"),
    )


def outcomes(p: dict, history: list[dict]) -> dict:
    merged = dt.datetime.fromisoformat(p["mergedAt"].replace("Z", "+00:00"))
    end = merged + dt.timedelta(days=WINDOW_DAYS)
    sha = ((p.get("mergeCommit") or {}).get("oid") or "")[:7]
    num_ref = re.compile(rf"#{p['number']}\b")
    title = (p.get("title") or "").strip()
    revert = fix = False
    for c in history:
        when = dt.datetime.fromisoformat(c["committedDate"].replace("Z", "+00:00"))
        if not (merged < when <= end):
            continue
        if sha and c["oid"].startswith(sha):
            continue  # the PR's own merge commit
        msg = c["message"] or ""
        refs = bool(sha and sha in msg) or bool(num_ref.search(msg))
        is_revert = "revert" in msg.lower() and (refs or (title and f'Revert "{title}' in msg))
        if is_revert:
            revert = True
        elif refs and FIX_KW.search(msg):
            fix = True
    return {"revert": revert, "fix": fix, "event": revert or fix}


def fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    """Fisher exact test on [[a, b], [c, d]] (a,b = group1 events/non-events)."""
    n1, n2, k = a + b, c + d, a + c
    n = n1 + n2

    def p_of(x: int) -> float:
        return math.comb(n1, x) * math.comb(n2, k - x) / math.comb(n, k)

    lo, hi = max(0, k - n2), min(k, n1)
    p_obs = p_of(a)
    return min(1.0, sum(p for x in range(lo, hi + 1) if (p := p_of(x)) <= p_obs * (1 + 1e-9)))


def holm(pvals: dict[str, float]) -> dict[str, float]:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m, out, running = len(items), {}, 0.0
    for i, (key, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[key] = running
    return out


def feature_table(rows: list[dict]) -> list[dict]:
    """Exploratory: event rate with vs without each binary feature, Fisher + Holm."""
    feats = {
        "critical_paths": lambda r: "critical_paths" in r["reasons"],
        "large_change": lambda r: "large_change" in r["reasons"],
        "many_owners": lambda r: "many_owners" in r["reasons"],
        "too_many_files": lambda r: "too_many_files" in r["reasons"],
        "ci_not_success": lambda r: r["ci"] != "success",
        "no_test_changes": lambda r: "Source changes without test changes" in r["missing"],
        "no_linked_ticket": lambda r: "Agent PR without a linked issue/ticket" in r["missing"],
        **{f"agent_{s}": (lambda s: lambda r: r["source"] == s)(s) for s in SOURCES},
    }
    stats, pvals = {}, {}
    for name, fn in feats.items():
        yes = [r for r in rows if fn(r)]
        no = [r for r in rows if not fn(r)]
        if not yes or not no:
            continue
        a, c = sum(r["event"] for r in yes), sum(r["event"] for r in no)
        p = fisher_two_sided(a, len(yes) - a, c, len(no) - c)
        ry, rn = a / len(yes), c / len(no)
        stats[name] = {
            "feature": name,
            "n_with": len(yes),
            "rate_with": round(ry, 4),
            "n_without": len(no),
            "rate_without": round(rn, 4),
            "rate_ratio": round(ry / rn, 3) if rn else None,
            "p": round(p, 5),
        }
        pvals[name] = p
    for k, v in holm(pvals).items():
        stats[k]["p_holm"] = round(v, 5)
    return sorted(stats.values(), key=lambda s: s["p"])


def wilson(k: int, n: int, z: float = 1.645) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - m), min(1.0, c + m))


def ratio_ci(rows: list[dict], seed: int = 7, n_boot: int = 2000) -> tuple[float | None, float | None, float | None]:
    def ratio(rs):
        t1 = [r for r in rs if r["tier"] == "T1"]
        t3 = [r for r in rs if r["tier"] == "T3"]
        if not t1 or not t3:
            return None
        r1 = sum(r["event"] for r in t1) / len(t1)
        r3 = sum(r["event"] for r in t3) / len(t3)
        return (r3 / r1) if r1 > 0 else math.inf

    point = ratio(rows)
    by_repo = defaultdict(list)
    for r in rows:
        by_repo[r["repo"]].append(r)
    repos = list(by_repo)
    rng = random.Random(seed)
    boots = []
    for _ in range(n_boot):
        sample = [x for _ in repos for x in by_repo[rng.choice(repos)]]
        v = ratio(sample)
        if v is not None:
            boots.append(v)
    if not boots:
        return point, None, None
    boots.sort()
    return point, boots[int(0.05 * len(boots))], boots[int(0.95 * len(boots)) - 1]


def summarize(rows: list[dict], label: str) -> dict:
    out = {"label": label, "n": len(rows), "repos": len({r["repo"] for r in rows}), "tiers": {}}
    for t in ("T1", "T2", "T3"):
        rs = [r for r in rows if r["tier"] == t]
        k_ev = sum(r["event"] for r in rs)
        k_rv = sum(r["revert"] for r in rs)
        out["tiers"][t] = {
            "n": len(rs),
            "share": round(len(rs) / len(rows), 3) if rows else 0,
            "event_rate": round(k_ev / len(rs), 4) if rs else None,
            "event_ci90": [round(x, 4) for x in wilson(k_ev, len(rs))],
            "revert_rate": round(k_rv / len(rs), 4) if rs else None,
            "events": k_ev,
            "reverts": k_rv,
        }
    point, lo, hi = ratio_ci(rows)
    out["ratio_T3_T1"] = None if point is None else (round(point, 3) if point != math.inf else "inf")
    out["ratio_ci90"] = [lo, hi] if lo is None else [round(lo, 3), round(hi, 3) if hi != math.inf else "inf"]
    events = sum(r["event"] for r in rows)
    t1n, t3n = out["tiers"]["T1"]["n"], out["tiers"]["T3"]["n"]
    e1, e3 = out["tiers"]["T1"]["events"], out["tiers"]["T3"]["events"]
    out["fisher_p_T3_vs_T1"] = round(fisher_two_sided(e3, t3n - e3, e1, t1n - e1), 5) if t1n and t3n else None
    if t1n < 300 or t3n < 300 or events < 30:
        verdict = "inconclusive (sample too small)"
    elif point is not None and point >= 2.0 and lo is not None and lo > 1.0:
        verdict = "PASS"
    elif point is not None and point < 2.0:
        verdict = "FAIL"
    else:
        verdict = "inconclusive (CI lower bound <= 1)"
    out["events_total"] = events
    out["verdict"] = verdict
    return out


def cmd_evaluate(args) -> None:
    prs = read_jsonl(DATA / "prs.jsonl")
    cfg = Config()
    rows = []
    reasons = Counter()
    for p in prs:
        if not p.get("mergedAt"):
            continue
        hp = hist_path(p["repo"])
        if not hp.exists():
            continue
        inp = to_input(p)
        d = evaluate(inp, cfg)
        oc = outcomes(p, read_jsonl(hp))
        rows.append(
            {
                "repo": p["repo"],
                "number": p["number"],
                "source": p["source"],
                "split": split_of(p["repo"]),
                "tier": d.tier.value,
                "ci": inp.ci_state,
                "author_kind": d.author.kind.value,
                "reasons": [r.code for r in d.reasons],
                "missing": d.missing_evidence,
                **oc,
            }
        )
        if d.tier == Tier.T3:
            reasons.update(r.code for r in d.reasons)
    ci_cov = defaultdict(list)
    for r in rows:
        ci_cov[r["repo"]].append(r["ci"] != "none")
    ci_ok = {repo for repo, v in ci_cov.items() if sum(v) / len(v) >= 0.5}
    rows = [r for r in rows if r["repo"] in ci_ok]
    want = args.split
    sel = [r for r in rows if want == "all" or r["split"] == want]
    report = {
        "split": want,
        "summary": summarize(sel, want),
        "per_source": {s: summarize([r for r in sel if r["source"] == s], s)["tiers"] for s in SOURCES},
        "features_exploratory": feature_table(sel),
        "t3_reasons": reasons.most_common(),
        "author_kinds": Counter(r["author_kind"] for r in sel).most_common(),
        "missing_evidence": Counter(m for r in sel for m in r["missing"]).most_common(),
    }
    (DATA / f"report_{want}.json").write_text(json.dumps(report, indent=2))
    (DATA / f"rows_{want}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in sel))
    print(json.dumps(report, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--pages", type=int, default=3)
    sub.add_parser("repos")
    sub.add_parser("collect")
    s = sub.add_parser("history")
    s.add_argument("--max-pages", type=int, default=30)
    s = sub.add_parser("evaluate")
    s.add_argument("--split", choices=["tuning", "holdout", "all"], default="tuning")
    args = ap.parse_args()
    {"sample": cmd_sample, "repos": cmd_repos, "collect": cmd_collect, "history": cmd_history, "evaluate": cmd_evaluate}[
        args.cmd
    ](args)


if __name__ == "__main__":
    main()
