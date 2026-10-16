"""事件处理模块：定义 MC 客户端上报的事件与分发器。

事件由 bridge（HTTP 服务）接收后交由 EventDispatcher 分发给注册的处理器。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

# 事件类型常量（与 mc_client/bot.js 上报的 type 对应）
EVT_JOIN = "join"                    # 加入服务器
EVT_SPAWN = "spawn"                  # 出生/重连成功
EVT_KICKED = "kicked"                # 被踢出服务器
EVT_DEATH = "death"                  # 死亡
EVT_HEALTH_LOW = "health_low"        # 血量过低
EVT_RARE_ITEM = "rare_item"          # 获得稀有物品
EVT_CHAT = "chat"                    # 游戏内聊天
EVT_TICK = "tick"                    # 周期状态上报
EVT_EXIT = "exit"                    # 客户端进程退出（重连耗尽）
EVT_ERROR = "error"                  # 客户端错误


@dataclass
class MCEvent:
    type: str
    container_name: str
    data: dict[str, Any] = field(default_factory=dict)


Handler = Callable[[MCEvent], Awaitable[None]]


class EventDispatcher:
    """简单异步事件分发器。"""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = {}
        self._wildcards: list[Handler] = []
        self.log = logging.getLogger("mc_agent.events")

    def on(self, event_type: str, handler: Handler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def on_any(self, handler: Handler) -> None:
        self._wildcards.append(handler)

    async def dispatch(self, event: MCEvent) -> None:
        handlers = list(self._wildcards) + list(self._handlers.get(event.type, []))
        for handler in handlers:
            try:
                await handler(event)
            except Exception:
                self.log.exception("事件处理器异常: %s", event.type)
