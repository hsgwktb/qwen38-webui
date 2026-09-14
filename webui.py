"""Qwen3.8-27B Uncensored — chat WebUI + OpenAI-compatible gateway.

Serves the chat UI at `/` (read from index.html next to this file) and proxies
everything else to the local llama-server.

Auth model (so external agent tools can use it):
  * llama-server runs with --api-key, so the key is a real requirement.
  * A request carrying an Authorization header must carry the correct key,
    otherwise 401 — a misconfigured tool then fails loudly instead of silently.
  * A same-origin browser request with no header gets the key injected, so the
    bundled WebUI works without the user pasting anything.
  * `/` and `/__api_info` stay open: the page needs them to load, and the page
    must be able to display the key for copying.

Placeholders substituted at deploy time: __DEPLOY_KEY__, __ALIAS__
Run:  python webui.py        (listens on 127.0.0.1:8000)
"""
import sys
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

HERE = Path(__file__).resolve().parent
DEPLOY_KEY = "__DEPLOY_KEY__"
ALIAS = "__ALIAS__"
UPSTREAM = "http://127.0.0.1:8081"
PORT = 8000

try:
    UI_HTML = (HERE / "index.html").read_text(encoding="utf-8")
except OSError as e:
    sys.exit(f"读不到 index.html（应与 webui.py 同目录）：{e}")

# must stay reachable so the UI can load and discover the key
OPEN_PATHS = {"", "__api_info", "favicon.ico"}

app = FastAPI()

# trust_env=False 很关键，别删：httpx 默认会读环境变量、以及 Windows 注册表里的系统代理
# 设置（urllib.getproxies()），把发往 http://127.0.0.1:8081 的请求也交给代理转发。
# 代理连不上本机的 llama-server，就回一个 5xx（500/502）、而且响应体为空；
# WebUI 又会把这个 5xx 原样透传给浏览器，于是「测试连接」报 HTTP 500，
# 让人以为模型没起来，其实 llama-server 好得很。回环地址必须直连。
client = httpx.AsyncClient(
    timeout=httpx.Timeout(None), limits=httpx.Limits(max_connections=64),
    trust_env=False,
)

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
}


def _err(message, code, status, kind="upstream_error"):
    return JSONResponse(
        {"error": {"message": message, "type": kind, "code": code}},
        status_code=status, headers=CORS,
    )


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(UI_HTML)


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


@app.get("/__api_info")
async def api_info(request: Request):
    """Exact values an external agent tool needs, derived from the live host.

    Also reports whether the upstream is actually alive, so the page can say
    "llama-server 没在跑" at load time instead of only failing on a test click.
    """
    host = request.headers.get("host", "")
    try:
        r = await client.get(f"{UPSTREAM}/health",
                             headers={"authorization": f"Bearer {DEPLOY_KEY}"},
                             timeout=4)
        upstream_ok = r.status_code in (200, 401)   # 开了 --api-key 后 /health 返回 401
    except httpx.HTTPError:
        upstream_ok = False
    return JSONResponse({
        "base_url": f"https://{host}/v1" if host else "",
        "api_key": DEPLOY_KEY,
        "model": ALIAS,
        "upstream": UPSTREAM,
        "upstream_ok": upstream_ok,
    })


@app.api_route("/{path:path}", methods=["GET", "POST", "OPTIONS"])
async def proxy(path: str, request: Request):
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=CORS)

    if path not in OPEN_PATHS:
        auth = request.headers.get("authorization")
        if auth and auth.strip() != f"Bearer {DEPLOY_KEY}":
            return _err("Invalid API key", "invalid_api_key", 401,
                        "invalid_request_error")

    body = await request.body()
    drop = {"host", "content-length", "accept-encoding", "connection"}
    headers = {k: v for k, v in request.headers.items() if k.lower() not in drop}
    headers["authorization"] = f"Bearer {DEPLOY_KEY}"

    # 这里原来没有兜底：llama-server 没起来时 httpx 抛异常，FastAPI 直接回 500，
    # 前端只显示一句 "HTTP 500"，完全看不出是上游没运行。改成 502 + 可读原因。
    try:
        r = await client.send(
            client.build_request(request.method, f"{UPSTREAM}/{path}",
                                 headers=headers, content=body),
            stream=True,
        )
    except httpx.HTTPError as e:
        return _err(
            f"上游 llama-server 未响应（{UPSTREAM}）：{type(e).__name__}: {e}。"
            "请确认 llama-server 已启动且进程还在"
            "（在实例里执行 pgrep -af llama-server 看有没有），"
            "必要时重跑第 5 格。",
            "upstream_unreachable", 502,
        )

    hop = {"content-encoding", "transfer-encoding", "content-length", "connection"}
    out = {k: v for k, v in r.headers.items() if k.lower() not in hop}
    out.update(CORS)
    return StreamingResponse(
        r.aiter_raw(), status_code=r.status_code, headers=out,
        media_type=r.headers.get("content-type"),
    )


if __name__ == "__main__":
    print(f"webui listening on 127.0.0.1:{PORT} -> {UPSTREAM} (alias={ALIAS})", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
