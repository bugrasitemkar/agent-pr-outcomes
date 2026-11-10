"""Spike: verify the stack on a deployed Python Worker.

Checks: FastAPI routing, RS256 JWT signing with an existing key (PyJWT +
cryptography), outbound HTTP, D1 read/write, Queue produce + consume.
Throwaway code: the real worker is built after the spike passes.
"""

import json
import time
import traceback

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from workers import WorkerEntrypoint

app = FastAPI()


@app.exception_handler(Exception)
async def show_errors(request: Request, exc: Exception):  # spike only
    return PlainTextResponse("".join(traceback.format_exception(exc)), status_code=500)


@app.get("/")
async def root():
    return {"ok": True}


@app.get("/spike/jwt")
async def spike_jwt(request: Request):
    t0 = time.time()
    import jwt

    pem = str(request.scope["env"].SPIKE_PEM)
    t1 = time.time()
    now = int(time.time())
    token = jwt.encode({"iat": now - 60, "exp": now + 540, "iss": "spike"}, pem, algorithm="RS256")
    return {
        "ok": token.count(".") == 2,
        "import_ms": round((t1 - t0) * 1000),
        "sign_ms": round((time.time() - t1) * 1000),
    }


@app.get("/spike/http")
async def spike_http():
    from js import fetch, Object
    from pyodide.ffi import to_js

    t0 = time.time()
    opts = to_js({"headers": {"User-Agent": "review-router-spike"}}, dict_converter=Object.fromEntries)
    resp = await fetch("https://api.github.com/zen", opts)
    text = await resp.text()
    return {"ok": resp.status == 200, "status": resp.status, "body": text, "ms": round((time.time() - t0) * 1000)}


@app.get("/spike/d1")
async def spike_d1(request: Request):
    db = request.scope["env"].DB
    await db.prepare(
        "CREATE TABLE IF NOT EXISTS spike (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, at TEXT)"
    ).run()
    await db.prepare("INSERT INTO spike (source, at) VALUES (?, ?)").bind("http", str(time.time())).run()
    rows = await db.prepare("SELECT source, COUNT(*) AS n FROM spike GROUP BY source").all()
    res = rows.results
    errs = await db.prepare("SELECT at FROM spike WHERE source = 'queue_error' ORDER BY id DESC LIMIT 1").all()
    return {"ok": True, "rows": res.to_py() if hasattr(res, "to_py") else res, "last_queue_error": errs.results}


@app.get("/spike/queue")
async def spike_queue(request: Request):
    from js import Object
    from pyodide.ffi import to_js

    msg = {"source": "queue", "sent_at": str(time.time())}
    await request.scope["env"].JOBS.send(to_js(msg, dict_converter=Object.fromEntries))
    return {"ok": True, "sent": msg, "next": "open /spike/d1 in a few seconds; a 'queue' row should appear"}


# ---------------------------------------------------------------------------
# GitHub App setup (manifest flow) + webhook spike
# ---------------------------------------------------------------------------
import hashlib
import hmac

from fastapi.responses import HTMLResponse

BASE = "https://review-router-spike.bugrasitemkar.workers.dev"
MANIFEST = {
    "name": "Review Router Dev",
    "url": "https://github.com/review-router",
    "hook_attributes": {"url": f"{BASE}/webhook", "active": True},
    "redirect_url": f"{BASE}/setup/callback",
    "public": False,
    "default_permissions": {
        "pull_requests": "read",
        "checks": "write",
        "statuses": "read",
        "issues": "write",
        "metadata": "read",
        "single_file": "read",
    },
    "default_events": ["pull_request", "check_suite", "check_run", "status"],
    # Single-file permission needs its path(s); testing whether several are accepted.
    "single_file_name": ".github/CODEOWNERS",
    "single_file_paths": [".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS", ".github/review-router.yml"],
}


@app.get("/setup", response_class=HTMLResponse)
async def setup_page():
    manifest = json.dumps(MANIFEST).replace('"', "&quot;")
    return f"""<!doctype html><meta charset=utf-8><title>Review Router setup</title>
<body style="font-family:system-ui;max-width:560px;margin:48px auto;padding:0 16px">
<h2>Create the Review Router Dev GitHub App</h2>
<p>This creates a private test App owned by the <b>review-router</b> organization,
with the permissions and webhook already filled in. On the next page, click
<b>Create GitHub App</b>.</p>
<form action="https://github.com/organizations/review-router/settings/apps/new?state=rr" method="post">
<input type="hidden" name="manifest" value="{manifest}">
<button style="font-size:16px;padding:10px 16px">Continue to GitHub</button></form></body>"""


@app.get("/setup/callback", response_class=HTMLResponse)
async def setup_callback(code: str = ""):
    return f"""<!doctype html><meta charset=utf-8><title>Review Router setup</title>
<body style="font-family:system-ui;max-width:560px;margin:48px auto;padding:0 16px">
<h2>Almost done</h2><p>Copy this code and paste it back to Claude (it expires in 1 hour):</p>
<pre style="font-size:18px;padding:12px;background:#eee;color:#111">{code}</pre></body>"""


async def gh_fetch(url, token=None, method="GET", body=None, auth="Bearer"):
    from js import Object, fetch
    from pyodide.ffi import to_js

    headers = {
        "User-Agent": "review-router-dev",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"{auth} {token}"
    opts = {"method": method, "headers": headers}
    if body is not None:
        opts["body"] = json.dumps(body)
    resp = await fetch(url, to_js(opts, dict_converter=Object.fromEntries))
    text = await resp.text()
    return resp.status, text


async def installation_token(env, installation_id):
    import jwt

    now = int(time.time())
    app_jwt = jwt.encode({"iat": now - 60, "exp": now + 540, "iss": str(env.APP_ID)}, str(env.APP_PEM), algorithm="RS256")
    status, text = await gh_fetch(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens", app_jwt, "POST"
    )
    return json.loads(text)["token"]


async def ensure_tables(db):
    await db.prepare(
        "CREATE TABLE IF NOT EXISTS deliveries (id TEXT PRIMARY KEY, event TEXT, action TEXT, received_at TEXT, handler_ms INTEGER)"
    ).run()
    await db.prepare("CREATE TABLE IF NOT EXISTS spike_pr (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, result TEXT)").run()


@app.post("/webhook")
async def webhook(request: Request):
    t0 = time.time()
    env = request.scope["env"]
    raw = await request.body()
    sig = request.headers.get("x-hub-signature-256", "")
    expected = "sha256=" + hmac.new(str(env.WEBHOOK_SECRET).encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return PlainTextResponse("bad signature", status_code=401)
    event = request.headers.get("x-github-event", "")
    delivery = request.headers.get("x-github-delivery", "")
    payload = json.loads(raw)
    await ensure_tables(env.DB)
    if event == "pull_request":
        from js import Object
        from pyodide.ffi import to_js

        job = {
            "installation_id": payload["installation"]["id"],
            "owner": payload["repository"]["owner"]["login"],
            "repo": payload["repository"]["name"],
            "number": payload["pull_request"]["number"],
            "base_ref": payload["pull_request"]["base"]["ref"],
        }
        await env.JOBS.send(to_js(job, dict_converter=Object.fromEntries))
    ms = round((time.time() - t0) * 1000)
    await env.DB.prepare("INSERT OR IGNORE INTO deliveries VALUES (?, ?, ?, ?, ?)").bind(
        delivery, event, payload.get("action", ""), str(time.time()), ms
    ).run()
    return {"ok": True, "handler_ms": ms}


async def spike_pr_job(env, job):
    """Runs in the queue consumer: token, GraphQL file list, single-file reads."""
    out = {"job": job}
    token = await installation_token(env, job["installation_id"])
    q = """query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){pullRequest(number:$n){
      changedFiles files(first:100){nodes{path additions deletions changeType}}}}}"""
    st, text = await gh_fetch(
        "https://api.github.com/graphql", token, "POST",
        {"query": q, "variables": {"o": job["owner"], "r": job["repo"], "n": job["number"]}},
    )
    out["graphql_status"] = st
    out["graphql"] = json.loads(text)
    for path in (".github/CODEOWNERS", "CODEOWNERS", ".github/review-router.yml"):
        st, text = await gh_fetch(
            f"https://api.github.com/repos/{job['owner']}/{job['repo']}/contents/{path}?ref={job['base_ref']}", token
        )
        out[f"read:{path}"] = st
    return out


@app.get("/spike/deliveries")
async def spike_deliveries(request: Request):
    db = request.scope["env"].DB
    await ensure_tables(db)
    d = await db.prepare("SELECT * FROM deliveries ORDER BY received_at DESC LIMIT 10").all()
    p = await db.prepare("SELECT at, result FROM spike_pr ORDER BY id DESC LIMIT 3").all()
    return {"deliveries": d.results, "pr_jobs": [{"at": r["at"], "result": json.loads(r["result"])} for r in p.results]}


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        try:
            import asgi

            return await asgi.fetch(app, request, self.env)
        except BaseException:  # spike only: surface the error in the browser
            from workers import Response

            return Response(traceback.format_exc(), status=500)

    async def queue(self, batch, *args):
        db = self.env.DB
        await db.prepare("CREATE TABLE IF NOT EXISTS spike (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, at TEXT)").run()
        try:
            await db.prepare("INSERT INTO spike (source, at) VALUES (?, ?)").bind("queue_called", str(time.time())).run()
            for message in batch.messages:
                body = message.body.to_py() if hasattr(message.body, "to_py") else message.body
                if isinstance(body, dict) and "installation_id" in body:
                    await ensure_tables(db)
                    try:
                        result = await spike_pr_job(self.env, body)
                    except BaseException:
                        result = {"error": traceback.format_exc()[-1500:]}
                    await db.prepare("INSERT INTO spike_pr (at, result) VALUES (?, ?)").bind(
                        str(time.time()), json.dumps(result)
                    ).run()
                else:
                    await db.prepare("INSERT INTO spike (source, at) VALUES (?, ?)").bind("queue", str(time.time())).run()
                message.ack()
        except BaseException:
            await db.prepare("INSERT INTO spike (source, at) VALUES (?, ?)").bind(
                "queue_error", traceback.format_exc()[-1500:]
            ).run()
            raise
