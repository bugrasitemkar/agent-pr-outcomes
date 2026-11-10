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
                await db.prepare("INSERT INTO spike (source, at) VALUES (?, ?)").bind("queue", str(time.time())).run()
                print(json.dumps({"event": "queue_consumed"}))
                message.ack()
        except BaseException:
            await db.prepare("INSERT INTO spike (source, at) VALUES (?, ?)").bind(
                "queue_error", traceback.format_exc()[-1500:]
            ).run()
            raise
