"""通信桥：插件与 MC 客户端容器之间的 HTTP 通道。

方向一（客户端 → 插件）：插件启动 aiohttp server（默认 :31888），
  客户端容器（host 网络）把事件 POST 到 /event。
方向二（插件 → 客户端）：插件把命令 POST 到客户端的 /cmd 端口（每实例一个）。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Awaitable, Callable

import aiohttp
from aiohttp import web

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class BridgeServer:
    """接收 MC 客户端容器上报的事件。"""

    def __init__(self, port: int, handler: EventHandler, logger=None) -> None:
        self.port = port
        self.handler = handler
        self.log = logger
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        app = web.Application()
        app.router.add_post("/event", self._on_event)
        app.router.add_get("/health", self._on_health)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self.port)
        await site.start()
        if self.log:
            self.log.info("Bridge HTTP 服务已启动: 0.0.0.0:%d", self.port)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    async def _on_health(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def _on_event(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "bad json"}, status=400)
        try:
            await self.handler(payload)
        except Exception:
            if self.log:
                self.log.exception("处理 MC 事件失败")
        return web.json_response({"ok": True})


class BotClient:
    """向某个 MC 客户端容器下发命令。"""

    def __init__(self, port: int, timeout: float = 120.0) -> None:
        self.base = f"http://127.0.0.1:{port}"
        self.timeout = timeout

    async def command(self, cmd: str, args: dict[str, Any] | None = None,
                      timeout: float | None = None) -> dict[str, Any]:
        """执行一条游戏命令，返回 {"ok": bool, "result": str}。"""
        payload = {"id": uuid.uuid4().hex[:8], "cmd": cmd, "args": args or {}}
        try:
            timeout = aiohttp.ClientTimeout(total=timeout or self.timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(f"{self.base}/cmd", json=payload) as resp:
                    data = await resp.json(content_type=None)
                    if resp.status != 200:
                        return {"ok": False, "result": str(data.get("error", resp.status))}
                    return {
                        "ok": bool(data.get("ok", False)),
                        "result": str(data.get("result", "")),
                    }
        except asyncio.TimeoutError:
            return {"ok": False, "result": f"命令 {cmd} 超时"}
        except (aiohttp.ClientError, OSError) as e:
            return {"ok": False, "result": f"客户端不可达: {e}"}

    async def execute_actions(self, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """顺序执行决策产生的动作列表。"""
        results = []
        for action in actions or []:
            if not isinstance(action, dict):
                continue
            cmd = str(action.get("cmd", "")).strip()
            if not cmd:
                continue
            args = action.get("args") or {}
            res = await self.command(cmd, args if isinstance(args, dict) else {})
            results.append({"cmd": cmd, **res})
        return results

    async def status(self) -> dict[str, Any]:
        return await self.command("status", {}, timeout=15)
