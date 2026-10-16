"""群聊上下文管理：MC 实例注册表 + 群聊上下文缓存。

一个 Instance 对应一次「在某群聊中启动 MC 客户端」的绑定：
- stream_id / group_id：绑定的群聊会话
- container_name / bot_http_port：Docker 实例标识
- context：滚动保留的群聊上下文（供 LLM 决策注入）
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Optional


@dataclass
class Instance:
    """一个 MC 客户端实例及其绑定的群聊。"""

    stream_id: str
    group_id: str
    container_name: str
    bot_http_port: int
    mc_server: str
    mc_port: int
    username: str
    # 群聊上下文缓存: [{"sender": str, "text": str, "time": str}]
    context: Deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=30))
    status: str = "starting"  # starting / online / kicked / offline / error
    last_alert_ts: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def add_context(self, sender: str, text: str, time_str: str = "") -> None:
        self.context.append({"sender": sender, "text": text, "time": time_str})

    def readable_context(self, limit: int = 20) -> str:
        """把缓存的群聊上下文转成可读文本（注入提示词用）。"""
        lines = []
        for item in list(self.context)[-limit:]:
            prefix = f"[{item['time']}] " if item.get("time") else ""
            lines.append(f"{prefix}{item['sender']}: {item['text']}")
        return "\n".join(lines) if lines else "（暂无群聊记录）"


class InstanceRegistry:
    """管理所有 MC 实例（支持多群聊多实例，相互隔离）。"""

    def __init__(self, max_context: int = 30) -> None:
        self._instances: dict[str, Instance] = {}  # stream_id -> Instance
        self.max_context = max_context

    def create(
        self,
        stream_id: str,
        group_id: str,
        container_name: str,
        bot_http_port: int,
        mc_server: str,
        mc_port: int,
        username: str,
    ) -> Instance:
        inst = Instance(
            stream_id=stream_id,
            group_id=group_id,
            container_name=container_name,
            bot_http_port=bot_http_port,
            mc_server=mc_server,
            mc_port=mc_port,
            username=username,
        )
        inst.context = deque(maxlen=max(10, self.max_context))
        self._instances[stream_id] = inst
        return inst

    def get(self, stream_id: str) -> Optional[Instance]:
        return self._instances.get(stream_id)

    def get_by_container(self, container_name: str) -> Optional[Instance]:
        for inst in self._instances.values():
            if inst.container_name == container_name:
                return inst
        return None

    def remove(self, stream_id: str) -> Optional[Instance]:
        return self._instances.pop(stream_id, None)

    def all(self) -> list[Instance]:
        return list(self._instances.values())

    def __len__(self) -> int:
        return len(self._instances)
