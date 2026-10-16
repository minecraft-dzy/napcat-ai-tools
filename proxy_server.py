"""
napcat-ai-tools 公网代理服务器
部署在公网服务器上，为无公网环境的用户提供请求转发能力。
"""
from __future__ import annotations

import json
import logging
import os
import uuid as _uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import HTMLResponse

# ============================================================
# 配置
# ============================================================
DATA_DIR = Path(os.environ.get("PROXY_DATA_DIR", Path(__file__).parent / "data"))
UUID_FILE = DATA_DIR / "uuids.json"
PLEA_FILE = DATA_DIR / "plea_store.json"
LOG_FILE = DATA_DIR / "proxy.log"
DEFAULT_PORT = int(os.environ.get("PROXY_PORT", "8787"))

# ============================================================
# 日志
# ============================================================
DATA_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [proxy] %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
)
logger = logging.getLogger("napcat-proxy")

# ============================================================
# UUID 持久化存储
# ============================================================


def _load_uuids() -> dict[str, str]:
    """加载 UUID 映射表: {user_nickname -> uuid}"""
    if UUID_FILE.exists():
        return json.loads(UUID_FILE.read_text(encoding="utf-8"))
    return {}


def _save_uuids(data: dict[str, str]) -> None:
    UUID_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


_uuids: dict[str, str] = {}


def get_or_create_uuid(user_key: str) -> str:
    """获取或创建用户的永久 UUID。"""
    global _uuids
    if user_key in _uuids:
        return _uuids[user_key]
    new_uuid = str(_uuid.uuid4())
    _uuids[user_key] = new_uuid
    _save_uuids(_uuids)
    logger.info(f"新用户注册: {user_key} -> {new_uuid}")
    return new_uuid


def validate_uuid(uuid_str: str) -> str | None:
    """验证 UUID 是否已注册，返回对应的 user_key 或 None。"""
    global _uuids
    for key, val in _uuids.items():
        if val == uuid_str:
            return key
    return None


# ============================================================
# 请求日志
# ============================================================

_req_log: list[dict[str, Any]] = []


def log_request(uuid_str: str, method: str, path: str, status: int, duration_ms: float) -> None:
    _req_log.append({
        "uuid": uuid_str[:8] + "...",
        "method": method,
        "path": path,
        "status": status,
        "duration_ms": round(duration_ms, 1),
    })
    # 只保留最近 500 条
    if len(_req_log) > 500:
        del _req_log[:-500]


# ============================================================
# 生命周期
# ============================================================

http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client, _uuids, plea_store
    _uuids = _load_uuids()
    plea_store = _load_plea_store()
    logger.info(f"已加载 {len(_uuids)} 个用户 UUID, {len(plea_store)} 条求情记录")
    http_client = httpx.AsyncClient(follow_redirects=True, timeout=60)
    yield
    if http_client:
        await http_client.aclose()


app = FastAPI(title="NapCat AI Tools Proxy", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# 安全校验依赖
# ============================================================


def _verify_uuid(uuid_str: str) -> str:
    """校验 UUID 并返回 user_key。"""
    user_key = validate_uuid(uuid_str)
    if user_key is None:
        raise HTTPException(status_code=403, detail=f"未注册的 UUID: {uuid_str[:16]}...")
    return user_key


# ============================================================
# 管理接口
# ============================================================


@app.get("/health")
async def health():
    return {"status": "ok", "users": len(_uuids)}


@app.post("/register")
async def register(request: Request):
    """注册新用户，获取永久 UUID。"""
    body = await request.json()
    user_key = str(body.get("user_key", "")).strip()
    if not user_key:
        raise HTTPException(status_code=400, detail="user_key 不能为空")
    uuid_str = get_or_create_uuid(user_key)
    return {"uuid": uuid_str, "user_key": user_key, "message": "UUID 已分配，请妥善保存"}


@app.get("/logs")
async def get_logs():
    return {"count": len(_req_log), "logs": _req_log[-50:]}


# ============================================================
# 请求转发路由
# ============================================================

import time as _time


@app.post("/{uuid_str}/tts")
async def proxy_tts(uuid_str: str, request: Request):
    """代理 SiliconFlow TTS 语音合成请求。"""
    _verify_uuid(uuid_str)
    start = _time.time()
    try:
        body = await request.json()
        api_key = request.headers.get("X-Proxy-Api-Key", "")
        if not api_key:
            raise HTTPException(status_code=400, detail="缺少 X-Proxy-Api-Key")

        resp = await http_client.post(
            "https://api.siliconflow.cn/v1/audio/speech",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
        )
        log_request(uuid_str, "POST", "/tts", resp.status_code, (_time.time() - start) * 1000)

        if resp.status_code != 200:
            return Response(content=resp.text, status_code=resp.status_code, media_type="application/json")
        return Response(content=resp.content, media_type=resp.headers.get("content-type", "audio/mpeg"))
    except Exception as exc:
        log_request(uuid_str, "POST", "/tts", 500, (_time.time() - start) * 1000)
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/{uuid_str}/github-api")
async def proxy_github_api(uuid_str: str, request: Request):
    """代理 GitHub API 请求。"""
    _verify_uuid(uuid_str)
    start = _time.time()
    try:
        body = await request.json()
        target_url = body.get("url", "")
        target_method = (body.get("method") or "GET").upper()
        target_headers = body.get("headers") or {}
        target_body = body.get("body")

        if not target_url or not target_url.startswith("https://api.github.com/"):
            raise HTTPException(status_code=400, detail=f"不支持的 URL: {target_url}")

        resp = await http_client.request(
            method=target_method,
            url=target_url,
            headers={**target_headers, "User-Agent": "napcat-ai-tools-proxy"},
            content=target_body,
        )
        log_request(uuid_str, target_method, "/github-api", resp.status_code, (_time.time() - start) * 1000)
        return Response(
            content=resp.content if resp.status_code == 200 else resp.text,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "application/json"),
        )
    except Exception as exc:
        log_request(uuid_str, "POST", "/github-api", 500, (_time.time() - start) * 1000)
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/{uuid_str}/fetch-webpage")
async def proxy_fetch_webpage(uuid_str: str, request: Request):
    """代理网页抓取请求。"""
    _verify_uuid(uuid_str)
    start = _time.time()
    try:
        body = await request.json()
        target_url = body.get("url", "")
        if not target_url:
            raise HTTPException(status_code=400, detail="url 不能为空")

        resp = await http_client.get(target_url, headers={"User-Agent": "Mozilla/5.0 (compatible; MaiBot/1.0)"})
        log_request(uuid_str, "GET", "/fetch-webpage", resp.status_code, (_time.time() - start) * 1000)
        return Response(content=resp.text, status_code=resp.status_code, media_type="text/html")
    except Exception as exc:
        log_request(uuid_str, "GET", "/fetch-webpage", 500, (_time.time() - start) * 1000)
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/{uuid_str}/deepseek")
async def proxy_deepseek(uuid_str: str, request: Request):
    """代理 DeepSeek API 请求。"""
    _verify_uuid(uuid_str)
    start = _time.time()
    try:
        body = await request.json()
        api_key = request.headers.get("X-Proxy-Api-Key", "")
        if not api_key:
            raise HTTPException(status_code=400, detail="缺少 X-Proxy-Api-Key")

        resp = await http_client.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
        )
        log_request(uuid_str, "POST", "/deepseek", resp.status_code, (_time.time() - start) * 1000)
        return Response(
            content=resp.content if resp.status_code == 200 else resp.text,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "application/json"),
        )
    except Exception as exc:
        log_request(uuid_str, "POST", "/deepseek", 500, (_time.time() - start) * 1000)
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/{uuid_str}/github-releases")
async def proxy_github_releases(uuid_str: str, request: Request):
    """代理 GitHub Releases 检查请求。"""
    _verify_uuid(uuid_str)
    start = _time.time()
    try:
        resp = await http_client.get(
            "https://api.github.com/repos/minecraft-dzy/napcat-ai-tools/releases/latest",
            headers={"User-Agent": "napcat-ai-tools-proxy", "Accept": "application/vnd.github.v3+json"},
        )
        log_request(uuid_str, "GET", "/github-releases", resp.status_code, (_time.time() - start) * 1000)
        return Response(
            content=resp.content if resp.status_code == 200 else resp.text,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "application/json"),
        )
    except Exception as exc:
        log_request(uuid_str, "GET", "/github-releases", 500, (_time.time() - start) * 1000)
        raise HTTPException(status_code=502, detail=str(exc))


# ---- 求情系统 ----

_PLEA_STORE_FILE = DATA_DIR / "plea_store.json"


def _load_plea_store() -> dict[str, dict]:
    if _PLEA_STORE_FILE.exists():
        return json.loads(_PLEA_STORE_FILE.read_text(encoding="utf-8"))
    return {}


def _save_plea_store(data: dict[str, dict]) -> None:
    _PLEA_STORE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


plea_store: dict[str, dict] = {}


@app.post("/{uuid_str}/plea/push")
async def plea_push(uuid_str: str, request: Request):
    """Bot 推送求情数据到代理。"""
    _verify_uuid(uuid_str)
    body = await request.json()
    plea_id = body.get("plea_id", "")
    if not plea_id:
        raise HTTPException(status_code=400, detail="plea_id 不能为空")
    plea_store[plea_id] = {
        "plea_id": plea_id,
        "user_name": body.get("user_name", ""),
        "user_id": body.get("user_id", ""),
        "group_id": body.get("group_id", ""),
        "duration": body.get("duration", 0),
        "status": "open",
        "plea_text": "",
        "review_result": "",
        "ai_message": "",
        "uuid": uuid_str,
    }
    _save_plea_store(plea_store)
    logger.info(f"求情已推送到代理: {plea_id} (uuid={uuid_str[:16]}...)")
    return {"ok": True, "plea_id": plea_id}


@app.get("/{uuid_str}/plea/poll")
async def plea_poll(uuid_str: str):
    """Bot 轮询求情提交。返回第一个待审核的求情。"""
    _verify_uuid(uuid_str)
    for pid, data in plea_store.items():
        if data.get("uuid") == uuid_str and data.get("status") == "pending_review":
            return data
    return {"ok": True, "pending": False}


@app.post("/{uuid_str}/plea/update")
async def plea_update(uuid_str: str, request: Request):
    """Bot 更新求情状态（审核结果）。"""
    _verify_uuid(uuid_str)
    body = await request.json()
    plea_id = body.get("plea_id", "")
    if plea_id not in plea_store:
        raise HTTPException(status_code=404)
    for key in ("status", "review_result", "ai_message", "duration"):
        if key in body:
            plea_store[plea_id][key] = body[key]
    _save_plea_store(plea_store)
    return {"ok": True}


# 求情页面 HTML
_PLEA_FORM = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>向麦麦认错</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:#f0f4f8;display:flex;justify-content:center;align-items:center;min-height:100vh;padding:20px}
.card{background:#fff;border-radius:16px;padding:32px;max-width:480px;width:100%%;box-shadow:0 4px 24px rgba(0,0,0,.08)}
h1{font-size:22px;color:#1a1a2e;margin-bottom:8px}
.meta{color:#666;font-size:14px;margin-bottom:24px}
.meta span{background:#ffeaa7;padding:2px 8px;border-radius:4px}
textarea{width:100%%;height:140px;border:2px solid #dfe6e9;border-radius:10px;padding:14px;font-size:15px;resize:vertical;outline:none;transition:border .2s}
textarea:focus{border-color:#6c5ce7}
.btn{width:100%%;padding:14px;background:#6c5ce7;color:#fff;border:none;border-radius:10px;font-size:16px;cursor:pointer;margin-top:16px;transition:background .2s}
.btn:hover{background:#5a4bd1}
</style></head>
<body>
<div class="card">
<h1>向麦麦求情</h1>
<p class="meta">被禁言用户：<span>%s</span> &nbsp; 禁言时长：<b>%s</b> 秒</p>
<form method="POST" action="%s">
<textarea name="plea_text" placeholder="向麦麦认错求情，说点好听的..." required></textarea>
<button class="btn" type="submit">提交求情</button>
</form>
</div>
</body></html>"""

_PLEA_SUBMITTED = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>求情已提交</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:#f0f4f8;display:flex;justify-content:center;align-items:center;min-height:100vh;padding:20px}
.card{background:#fff;border-radius:16px;padding:32px;max-width:480px;width:100%%;box-shadow:0 4px 24px rgba(0,0,0,.08);text-align:center}
h1{font-size:22px;color:#00b894;margin-bottom:12px}
p{color:#636e72;font-size:15px}
</style></head>
<body>
<div class="card">
<h1>求情已提交</h1>
<p>你的求情已成功提交，麦麦将尽快审核处理。</p>
</div>
</body></html>"""

_PLEA_CLOSED = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>求情已关闭</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:#f0f4f8;display:flex;justify-content:center;align-items:center;min-height:100vh;padding:20px}
.card{background:#fff;border-radius:16px;padding:32px;max-width:480px;width:100%%;box-shadow:0 4px 24px rgba(0,0,0,.08);text-align:center}
h1{font-size:22px;margin-bottom:12px}
.approved h1{color:#00b894}
.denied h1{color:#d63031}
.closed h1{color:#636e72}
p{color:#636e72;font-size:15px;margin-bottom:8px}
.ai-msg{background:#f8f9fa;border-radius:8px;padding:16px;margin:16px 0;font-size:15px;color:#2d3436;text-align:left;white-space:pre-wrap}
</style></head>
<body>
<div class="card %s">
<h1>%s</h1>
<p>%s</p>
%s
</div>
</body></html>"""


@app.api_route("/{uuid_str}/plea/{plea_id}", methods=["GET", "POST"])
async def plea_page(request: Request, uuid_str: str, plea_id: str):
    """代理求情页面（完整渲染表单和结果）。"""
    _verify_uuid(uuid_str)

    if request.method == "POST":
        data = plea_store.get(plea_id)
        if not data or data.get("status") != "open":
            return HTMLResponse(_PLEA_CLOSED % ("closed", "求情已关闭", "该求情链接不存在或已过期。", ""), status_code=410)

        form = await request.form()
        text = (form.get("plea_text", "") or "").strip()
        if not text or len(text) < 2:
            return HTMLResponse(
                _PLEA_FORM % (data["user_name"], data["duration"], f"/{uuid_str}/plea/{plea_id}")
                + "<script>alert('求情内容不能为空');</script>"
            )

        data["plea_text"] = text
        data["status"] = "pending_review"
        _save_plea_store(plea_store)
        logger.info(f"求情已提交: {plea_id} text={text[:50]}...")
        return HTMLResponse(_PLEA_SUBMITTED)

    # GET
    data = plea_store.get(plea_id)
    if not data:
        return HTMLResponse(_PLEA_CLOSED % ("closed", "求情已关闭", "该求情链接不存在。", ""), status_code=410)

    status = data.get("status", "open")
    if status == "open":
        return HTMLResponse(_PLEA_FORM % (data["user_name"], data["duration"], f"/{uuid_str}/plea/{plea_id}"))
    if status == "pending_review" or status == "pending_ai":
        return HTMLResponse(_PLEA_SUBMITTED)

    ai_msg = str(data.get("ai_message") or "").strip()
    if status == "approved":
        msg = f'<div class="ai-msg">麦麦说：{ai_msg}</div>' if ai_msg else ""
        return HTMLResponse(_PLEA_CLOSED % ("approved", "求情已通过", "麦麦已解除你的禁言。" + (f" 附言：{ai_msg}" if ai_msg else ""), msg))
    if status == "denied":
        msg = f'<div class="ai-msg">麦麦说：{ai_msg}</div>' if ai_msg else ""
        extra = ""
        if "extended" in str(data.get("review_result", "")):
            extra = f" 禁言已延长至 {data.get('duration', 0)} 秒。"
        return HTMLResponse(_PLEA_CLOSED % ("denied", "求情被拒绝", "麦麦拒绝了你的求情。" + extra, msg))

    return HTMLResponse(_PLEA_CLOSED % ("closed", "求情已关闭", "该求情链接已失效或已被处理。", ""))


# ---- 下载代理 ----

@app.get("/{uuid_str}/github-download/{tag}/{filename}")
async def proxy_download(uuid_str: str, tag: str, filename: str):
    """代理下载 GitHub Release 附件（二进制流）。"""
    _verify_uuid(uuid_str)
    start = _time.time()
    download_url = f"https://github.com/minecraft-dzy/napcat-ai-tools/releases/download/{tag}/{filename}"
    logger.info(f"代理下载: {download_url}")
    try:
        resp = await http_client.get(download_url, headers={"User-Agent": "napcat-ai-tools-proxy"}, follow_redirects=True)
        resp.raise_for_status()
        log_request(uuid_str, "GET", f"/github-download/{tag}/{filename}", 200, (_time.time() - start) * 1000)
        return Response(content=resp.content, media_type="application/zip")
    except Exception as exc:
        log_request(uuid_str, "GET", f"/github-download/{tag}/{filename}", 502, (_time.time() - start) * 1000)
        raise HTTPException(status_code=502, detail=str(exc))


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=DEFAULT_PORT)
