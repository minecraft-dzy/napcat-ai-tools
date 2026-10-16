"""MC-Agent — Minecraft 智能体插件（MaiBot v1.0.4 / SDK 2.x）

功能：
- planner 工具：在群聊中启动/停止 Minecraft 无头客户端（Docker，内存硬限制 1.5GB）
- 群聊上下文绑定：启动时拉取群聊历史，后续消息按策略同步
- 事件驱动决策：被踢出/稀有物品/低血量/死亡/游戏内被喊话 → 注入提示词调 DeepSeek → 执行游戏动作
- 真人聊天交互：游戏内聊天 + 回复群聊消息
- 内存监控：定期日志、超阈值群聊告警、支持工具查询
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any

from maibot_sdk import EventHandler, Field, MaiBotPlugin, PluginConfigBase, Tool
from maibot_sdk.types import EventType, ToolParameterInfo, ToolParamType

# 确保本地包可导入（runner 会临时把插件目录加入 sys.path，这里兜底）
_PLUGIN_DIR = Path(__file__).resolve().parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

from core.bridge import BotClient, BridgeServer  # noqa: E402
from core.context import Instance, InstanceRegistry  # noqa: E402
from core.docker_manager import DockerManager  # noqa: E402
from core.events import (  # noqa: E402
    EVT_CHAT,
    EVT_DEATH,
    EVT_ERROR,
    EVT_EXIT,
    EVT_HEALTH_LOW,
    EVT_JOIN,
    EVT_KICKED,
    EVT_RARE_ITEM,
    EVT_SPAWN,
    EVT_TICK,
    MCEvent,
)
from core.llm import ACTIONS_DOC, SYSTEM_PROMPT, LLMClient, LLMError, decide_with_retry  # noqa: E402
from utils.helpers import now_str, parse_event_reason, truncate  # noqa: E402

logger = logging.getLogger("mc_agent.plugin")

RARE_ITEMS = [
    "diamond", "netherite", "ancient_debris", "elytra", "totem_of_undying",
    "nether_star", "beacon", "enchanted_golden_apple", "trident", "shulker_shell",
    "heart_of_the_sea", "nautilus_shell", "mending", "music_disc",
]


# ============================ 配置模型 ============================

class PluginSectionConfig(PluginConfigBase):
    __ui_label__ = "插件"
    __ui_icon__ = "package"
    __ui_order__ = 0
    enabled: bool = Field(default=True, description="是否启用插件")
    config_version: str = Field(default="1.0.0", description="配置版本")


class MCConfig(PluginConfigBase):
    __ui_label__ = "MC 客户端"
    __ui_icon__ = "box"
    __ui_order__ = 1
    docker_image: str = Field(default="mc-client:latest", description="MC 客户端镜像")
    memory_limit: str = Field(default="1536m", description="容器内存限制")
    memory_swap: str = Field(default="2048m", description="容器内存+swap 限制")
    plugin_http_port: int = Field(default=31888, description="插件事件接收端口")
    bot_http_port_base: int = Field(default=31889, description="客户端控制端口起始值")
    offline_mode: bool = Field(default=True, description="离线认证模式")
    auto_reconnect: bool = Field(default=True, description="被踢出后自动重连")
    max_reconnect_attempts: int = Field(default=5, description="最大重连次数")
    max_instances: int = Field(default=3, description="最大同时运行实例数")
    default_username: str = Field(default="MaiBotPlayer", description="默认游戏昵称")
    default_server_port: int = Field(default=25565, description="默认 MC 服务器端口")


class LLMConfig(PluginConfigBase):
    __ui_label__ = "LLM"
    __ui_icon__ = "brain"
    __ui_order__ = 2
    mode: str = Field(default="direct", description="host=主程序模型 / direct=直连 DeepSeek2")
    api_key: str = Field(default="", description="DeepSeek2 提供商 API Key（direct 模式）")
    base_url: str = Field(default="https://api.deepseek.com", description="DeepSeek2 API 地址")
    model: str = Field(default="deepseek-flash", description="direct 模式模型名")
    host_model: str = Field(default="deepseek-flash", description="host 模式模型名（DeepSeek2 下挂）")
    temperature: float = Field(default=0.7, description="温度")
    max_tokens: int = Field(default=1024, description="最大 token")
    timeout: int = Field(default=60, description="请求超时（秒）")


class ContextConfig(PluginConfigBase):
    __ui_label__ = "群聊上下文"
    __ui_icon__ = "messages-square"
    __ui_order__ = 3
    history_limit: int = Field(default=200, description="启动时拉取群聊历史条数（作为机器人初始记忆）")
    sync_mode: str = Field(default="at_only", description="群聊消息同步策略: off/at_only/all")
    sync_keywords: str = Field(default="", description="额外同步关键词（逗号分隔）")
    max_context_messages: int = Field(default=50, description="注入提示词的最大上下文条数")


class PlannerConfig(PluginConfigBase):
    __ui_label__ = "决策"
    __ui_icon__ = "compass"
    __ui_order__ = 4
    feedback_to_chat: bool = Field(default=True, description="决策结果反馈到群聊")
    trigger_maisaka: bool = Field(default=True, description="事件触发 maisaka planner")
    relay_game_chat: bool = Field(default=True, description="游戏内聊天转发到群聊")
    health_low_threshold: int = Field(default=8, description="低血量阈值（半颗心=1）")
    status_decision_interval: int = Field(default=300, description="定期状态决策间隔（秒），0 关闭")
    decision_timeout: int = Field(default=180, description="单次决策执行超时（秒）")


class MonitorConfig(PluginConfigBase):
    __ui_label__ = "监控"
    __ui_icon__ = "activity"
    __ui_order__ = 5
    enabled: bool = Field(default=True, description="启用内存监控")
    interval: int = Field(default=60, description="监控间隔（秒）")
    alert_threshold_mb: float = Field(default=1228, description="内存告警阈值（MB）")
    alert_cooldown: int = Field(default=600, description="告警冷却（秒）")


class MCAgentConfig(PluginConfigBase):
    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    mc: MCConfig = Field(default_factory=MCConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    planner: PlannerConfig = Field(default_factory=PlannerConfig)
    monitor: MonitorConfig = Field(default_factory=MonitorConfig)


# ============================ 插件主体 ============================

class MCAgentPlugin(MaiBotPlugin):
    config_model = MCAgentConfig

    def __init__(self) -> None:
        super().__init__()
        self.docker: DockerManager | None = None
        self.llm: LLMClient | None = None
        self.registry: InstanceRegistry | None = None
        self.dispatcher = None
        self.bridge: BridgeServer | None = None
        self._monitor_task: asyncio.Task | None = None
        self._decision_tasks: dict[str, asyncio.Task] = {}
        self._restart_counts: dict[str, int] = {}
        self._last_status_decision: dict[str, float] = {}

    def get_components(self) -> list[dict[str, Any]]:
        """收集组件声明；把装饰器 kwargs 的内层 metadata 提升到外层。

        SDK 装饰器把 visibility 等自定义 kwargs 存进 ComponentInfo.metadata（内层 dict），
        而宿主读取的是 model_dump 后的外层 metadata，这里手动拍平保证 visibility 生效，
        否则工具在 maisaka planner 里是 deferred 状态，LLM 默认看不到 mc_planner。
        """
        components = super().get_components()
        for comp in components:
            metadata = comp.get("metadata")
            if isinstance(metadata, dict) and isinstance(metadata.get("metadata"), dict):
                inner_metadata = metadata.pop("metadata")
                metadata.update(inner_metadata)
        return components

    # ---------- 生命周期 ----------

    async def on_load(self) -> None:
        cfg = self.config
        self.docker = DockerManager(cfg.mc.docker_image, cfg.mc.memory_limit,
                                    cfg.mc.memory_swap, logger=self.ctx.logger)
        self.llm = LLMClient(self.ctx, cfg.llm, logger=self.ctx.logger)
        self.registry = InstanceRegistry(max_context=250)

        from core.events import EventDispatcher
        self.dispatcher = EventDispatcher()
        self.dispatcher.on(EVT_JOIN, self._on_join)
        self.dispatcher.on(EVT_SPAWN, self._on_spawn)
        self.dispatcher.on(EVT_KICKED, self._on_kicked)
        self.dispatcher.on(EVT_DEATH, self._on_death)
        self.dispatcher.on(EVT_HEALTH_LOW, self._on_health_low)
        self.dispatcher.on(EVT_RARE_ITEM, self._on_rare_item)
        self.dispatcher.on(EVT_CHAT, self._on_game_chat)
        self.dispatcher.on(EVT_TICK, self._on_tick)
        self.dispatcher.on(EVT_EXIT, self._on_exit)
        self.dispatcher.on(EVT_ERROR, self._on_error)

        self.bridge = BridgeServer(cfg.mc.plugin_http_port, self._handle_event_payload,
                                   logger=self.ctx.logger)
        try:
            await self.bridge.start()
        except OSError as e:
            self.ctx.logger.error("Bridge 端口 %d 启动失败: %s", cfg.mc.plugin_http_port, e)

        if cfg.monitor.enabled:
            self._monitor_task = asyncio.create_task(self._monitor_loop())

        self.ctx.logger.info("MC-Agent 插件已加载（llm=%s, image=%s）",
                             cfg.llm.mode, cfg.mc.docker_image)

    async def on_unload(self) -> None:
        for task in self._decision_tasks.values():
            task.cancel()
        self._decision_tasks.clear()
        if self._monitor_task:
            self._monitor_task.cancel()
            self._monitor_task = None
        if self.bridge:
            await self.bridge.stop()
        # 停止所有实例容器
        if self.docker and self.registry:
            for inst in self.registry.all():
                try:
                    await self.docker.stop_client(inst.container_name, timeout=10)
                except Exception:
                    pass
        self.ctx.logger.info("MC-Agent 插件已卸载")

    async def on_config_update(self, scope: str, config_data: dict, version: str) -> None:
        if scope == "self":
            self.ctx.logger.info("MC-Agent 配置已更新 (v%s)", version)

    # ---------- planner 工具 ----------

    @Tool(
        "mc_planner",
        description="启动/停止/重启 Minecraft 客户端，让机器人以真人玩家身份加入原版生存服务器，并绑定当前群聊（启动后机器人会感知本群聊天上下文并在游戏内自主生存）",
        visibility="visible",
        parameters=[
            ToolParameterInfo(name="action", param_type=ToolParamType.STRING,
                              description="动作: start（启动）/ stop（停止）/ status（查看状态）",
                              required=True, enum_values=["start", "stop", "status"]),
            ToolParameterInfo(name="server_host", param_type=ToolParamType.STRING,
                              description="MC 服务器地址（start 时必填）", required=False),
            ToolParameterInfo(name="server_port", param_type=ToolParamType.INTEGER,
                              description="MC 服务器端口，默认 25565", required=False),
            ToolParameterInfo(name="username", param_type=ToolParamType.STRING,
                              description="游戏内昵称，默认 MaiBotPlayer", required=False),
        ],
    )
    async def tool_mc_planner(self, action: str = "status", server_host: str = "",
                              server_port: int = 0, username: str = "", **kwargs: Any) -> dict:
        action = (action or "status").strip().lower()
        stream_id = str(kwargs.get("stream_id") or kwargs.get("chat_id") or "").strip()
        group_id = str(kwargs.get("group_id") or "").strip()
        if not stream_id:
            return self._tool_fail("无法确定当前群聊会话（缺少 stream_id）")

        if action == "status":
            return await self._tool_status()
        if action == "stop":
            return await self._tool_stop(stream_id)
        if action == "start":
            if not server_host:
                return self._tool_fail("缺少 MC 服务器地址（server_host）")
            return await self._tool_start(stream_id, group_id, server_host,
                                          int(server_port or self.config.mc.default_server_port),
                                          username.strip() or self.config.mc.default_username)
        return self._tool_fail(f"未知动作: {action}")

    @Tool(
        "mc_memory_status",
        description="查询 MC 客户端 Docker 容器的内存占用与运行状态",
        visibility="visible",
        parameters=[],
    )
    async def tool_mc_memory_status(self, **kwargs: Any) -> dict:
        stats = await self.docker.stats_all()
        if not stats:
            return self._tool_ok("当前没有运行中的 MC 客户端容器")
        lines = ["MC 客户端容器内存状态（限制 1.5GB）:"]
        for s in stats:
            usage = f"{s['usage_mb']:.0f}MB" if s["usage_mb"] is not None else "未知"
            state = "运行中" if s["running"] else "已停止"
            lines.append(f"- {s['name']}: {state}, 内存 {usage}")
        return self._tool_ok("\n".join(lines))

    async def _tool_start(self, stream_id: str, group_id: str, server_host: str,
                          server_port: int, username: str) -> dict:
        cfg = self.config
        if len(self.registry) >= cfg.mc.max_instances:
            return self._tool_fail(f"已达最大实例数 {cfg.mc.max_instances}")
        if self.registry.get(stream_id):
            return self._tool_fail("当前群聊已绑定一个 MC 客户端，请先发送停止指令")
        if not await self.docker.image_exists():
            return self._tool_fail(
                f"镜像 {cfg.mc.docker_image} 不存在，请在服务器上执行: "
                f"cd 插件目录/mc_client && docker build -t {cfg.mc.docker_image} ."
            )

        # 分配容器名与端口
        idx = len(self.registry) + 1
        while True:
            name = f"mc-agent-{idx}"
            port = cfg.mc.bot_http_port_base + idx - 1
            if not self.registry.get_by_container(name) and not await self.docker.container_exists(name):
                break
            idx += 1

        ok, msg = await self.docker.start_client(
            name, server_host, server_port, username, port,
            cfg.mc.plugin_http_port, cfg.mc.offline_mode,
        )
        if not ok:
            return self._tool_fail(f"容器启动失败: {truncate(msg, 200)}")

        inst = self.registry.create(stream_id, group_id, name, port,
                                    server_host, server_port, username)
        self._restart_counts[stream_id] = 0

        # 拉取群聊历史作为初始上下文
        history_text = await self._fetch_chat_history(stream_id)
        if history_text:
            inst.add_context("（启动时的群聊历史）", truncate(history_text, 1500), now_str())

        await self._send_group(inst, f"正在启动 Minecraft 客户端（{username} → {server_host}:{server_port}），容器 {name} 已创建（内存限制 1.5GB），加入后我会说一声～")
        self.ctx.logger.info("MC 实例已启动: %s -> %s (%s:%d)", stream_id, name, server_host, server_port)
        return self._tool_ok(f"MC 客户端容器 {name} 启动中，绑定群聊 {group_id or stream_id}")

    async def _tool_stop(self, stream_id: str) -> dict:
        inst = self.registry.get(stream_id)
        if not inst:
            return self._tool_fail("当前群聊没有绑定 MC 客户端")
        task = self._decision_tasks.pop(stream_id, None)
        if task:
            task.cancel()
        ok, msg = await self.docker.stop_client(inst.container_name)
        await self.docker.remove_container(inst.container_name, force=True)
        self.registry.remove(stream_id)
        if ok:
            await self._send_group(inst, "MC 客户端已停止，下次想玩再叫我～")
            return self._tool_ok("MC 客户端已停止")
        return self._tool_fail(f"停止失败: {truncate(msg, 150)}")

    async def _tool_status(self) -> dict:
        stats = await self.docker.stats_all()
        if not stats:
            return self._tool_ok("当前没有 MC 客户端实例")
        lines = []
        for s in stats:
            usage = f"{s['usage_mb']:.0f}MB" if s["usage_mb"] is not None else "?"
            lines.append(f"{s['name']}({'运行中' if s['running'] else '已停止'}, {usage})")
        return self._tool_ok("MC 客户端: " + ", ".join(lines))

    @staticmethod
    def _tool_ok(content: str, **kw) -> dict:
        return {"success": True, "name": "mc_planner", "content": content, **kw}

    @staticmethod
    def _tool_fail(msg: str) -> dict:
        return {"success": False, "name": "mc_planner", "content": "", "error": msg, "message": msg}

    # ---------- 群聊消息处理 ----------

    @EventHandler(
        "mc_agent_message_handler",
        description="监听群聊消息：维护 MC 绑定群聊的上下文，并按策略把消息同步给 MC LLM",
        event_type=EventType.ON_MESSAGE,
        intercept_message=False,
        weight=0,
    )
    async def on_message(self, message: dict | None = None, **kwargs) -> tuple:
        """返回 (should_continue, intercepted, None, None, None) 元组，不拦截消息。"""
        try:
            if not message or not self.registry:
                return True, False, None, None, None
            stream_id = str(message.get("session_id") or "")
            inst = self.registry.get(stream_id)
            if not inst:
                return True, False, None, None, None

            text = str(message.get("processed_plain_text") or "").strip()
            if not text:
                return True, False, None, None, None
            info = message.get("message_info") or {}
            user = (info.get("user_info") or {}).get("user_nickname") or "群友"
            group = (info.get("group_info") or {}).get("group_id") or inst.group_id
            inst.add_context(user, truncate(text, 200), now_str())

            if self._should_sync(message, text):
                nickname = inst.username
                event_desc = f"群友 {user} 在 QQ 群（{group}）里说：{text}"
                self._spawn_decision(inst, event_desc, group_notify=False)
        except Exception:
            logger.exception("on_message 处理异常")
        return True, False, None, None, None

    def _should_sync(self, message: dict, text: str) -> bool:
        mode = self.config.context.sync_mode
        if mode == "all":
            return True
        if mode == "off":
            return False
        # at_only
        if message.get("is_mentioned") or message.get("is_at"):
            return True
        keywords = [k.strip() for k in (self.config.context.sync_keywords or "").split(",") if k.strip()]
        return any(k in text for k in keywords)

    # ---------- MC 事件处理 ----------

    async def _handle_event_payload(self, payload: dict) -> None:
        evt = MCEvent(
            type=str(payload.get("type") or ""),
            container_name=str(payload.get("container") or ""),
            data=payload.get("data") or {},
        )
        if not evt.type:
            return
        await self.dispatcher.dispatch(evt)

    def _inst_by_container(self, container_name: str) -> Instance | None:
        return self.registry.get_by_container(container_name) if self.registry else None

    async def _on_join(self, evt: MCEvent) -> None:
        inst = self._inst_by_container(evt.container_name)
        if not inst:
            return
        inst.status = "online"
        self._restart_counts[inst.stream_id] = 0
        await self._send_group(inst, f"MC 机器人 {inst.username} 已加入服务器 {inst.mc_server}:{inst.mc_port}，大家可以在游戏里找它玩，也可以在这里 @ 它安排任务～")
        await self._trigger_maisaka(inst, f"MC 机器人 {inst.username} 刚刚加入了 Minecraft 服务器，跟大家打个招呼吧")

    async def _on_spawn(self, evt: MCEvent) -> None:
        inst = self._inst_by_container(evt.container_name)
        if inst:
            inst.status = "online"

    async def _on_kicked(self, evt: MCEvent) -> None:
        inst = self._inst_by_container(evt.container_name)
        if not inst:
            return
        inst.status = "kicked"
        reason = parse_event_reason(str(evt.data.get("reason") or ""))
        await self._send_group(inst, f"⚠️ MC 机器人 {inst.username} 被踢出了服务器：{truncate(reason, 100)}")
        if self.config.mc.auto_reconnect and not evt.data.get("reconnect_exhausted"):
            await self._trigger_maisaka(inst, f"MC 机器人被踢出服务器（原因：{reason}），即将自动重连")
        else:
            await self._on_exit(MCEvent(EVT_EXIT, evt.container_name,
                                        {"reason": reason, "kicked_reason": reason}))

    async def _on_death(self, evt: MCEvent) -> None:
        inst = self._inst_by_container(evt.container_name)
        if not inst:
            return
        cause = truncate(str(evt.data.get("cause") or "未知原因"), 100)
        await self._send_group(inst, f"💀 MC 机器人 {inst.username} 死亡了（{cause}），已自动重生。")
        self._spawn_decision(inst, f"你死亡了（原因：{cause}），已自动重生在出生点。请决定接下来做什么（比如回去捡东西、补充装备、先吃饭）。")

    async def _on_health_low(self, evt: MCEvent) -> None:
        inst = self._inst_by_container(evt.container_name)
        if not inst:
            return
        self._spawn_decision(inst, f"警告：你的血量过低（{evt.data.get('hp', '?')}/{evt.data.get('max_hp', 20)}），请立即决策保命（吃东西/逃跑/躲避）。")

    async def _on_rare_item(self, evt: MCEvent) -> None:
        inst = self._inst_by_container(evt.container_name)
        if not inst:
            return
        item = str(evt.data.get("item") or "未知物品")
        await self._send_group(inst, f"✨ MC 机器人 {inst.username} 获得了稀有物品：{item}！")
        self._spawn_decision(inst, f"你刚刚获得了稀有物品 {item}！可以在游戏里炫耀一下（say_in_game），并决定接下来做什么。")

    async def _on_game_chat(self, evt: MCEvent) -> None:
        inst = self._inst_by_container(evt.container_name)
        if not inst:
            return
        player = str(evt.data.get("player") or "玩家")
        text = truncate(str(evt.data.get("message") or ""), 150)
        if self.config.planner.relay_game_chat:
            await self._send_group(inst, f"[MC] {player}: {text}")
        # 游戏内有人对机器人说话（包含昵称或 @）→ 触发决策
        if inst.username.lower() in text.lower() or f"@{inst.username}" in text:
            self._spawn_decision(inst, f"游戏内玩家 {player} 对你说：{text}。请在游戏内自然地回复（say_in_game 或 say 动作），并根据内容决定是否行动。")

    async def _on_tick(self, evt: MCEvent) -> None:
        inst = self._inst_by_container(evt.container_name)
        if not inst:
            return
        inst.status = "online"
        interval = self.config.planner.status_decision_interval
        if interval <= 0:
            return
        now = time.time()
        last = self._last_status_decision.get(inst.stream_id, 0)
        if now - last >= interval:
            self._last_status_decision[inst.stream_id] = now
            state = evt.data
            self._spawn_decision(
                inst,
                "定期状态检查：请根据当前状态自主安排下一步生存活动（维持 1~2 个动作即可）。",
                game_state_override=state if state else None,
            )

    async def _on_exit(self, evt: MCEvent) -> None:
        inst = self._inst_by_container(evt.container_name)
        if not inst:
            return
        if not self.config.mc.auto_reconnect:
            inst.status = "offline"
            self.registry.remove(inst.stream_id)
            await self._send_group(inst, f"MC 客户端已退出且未开启自动重连：{truncate(str(evt.data.get('reason') or ''), 100)}")
            return
        count = self._restart_counts.get(inst.stream_id, 0)
        if count >= self.config.mc.max_reconnect_attempts:
            inst.status = "error"
            await self._send_group(inst, f"❌ MC 客户端重连 {count} 次均失败，已放弃。可再次用 planner 工具重启。")
            return
        self._restart_counts[inst.stream_id] = count + 1
        await self._send_group(inst, f"MC 客户端异常退出，正在尝试第 {count + 1} 次重启容器…")
        ok, _ = await self.docker.restart_container(inst.container_name)
        if not ok:
            inst.status = "error"
            await self._send_group(inst, "容器重启失败，请检查 docker 日志。")

    async def _on_error(self, evt: MCEvent) -> None:
        inst = self._inst_by_container(evt.container_name)
        if inst:
            self.ctx.logger.warning("MC 客户端错误 (%s): %s", inst.container_name,
                                    truncate(str(evt.data.get("message") or ""), 200))

    # ---------- 决策流水线 ----------

    def _spawn_decision(self, inst: Instance, event_desc: str,
                        group_notify: bool = True, game_state_override: dict | None = None) -> None:
        old = self._decision_tasks.get(inst.stream_id)
        if old and not old.done():
            return  # 已有决策在跑，避免并发刷屏
        task = asyncio.create_task(
            self._run_decision(inst, event_desc, group_notify, game_state_override)
        )
        self._decision_tasks[inst.stream_id] = task
        task.add_done_callback(lambda _t: self._decision_tasks.pop(inst.stream_id, None))

    async def _run_decision(self, inst: Instance, event_desc: str,
                            group_notify: bool = True, game_state_override: dict | None = None) -> None:
        try:
            async with asyncio.timeout(self.config.planner.decision_timeout):
                await self._decision_flow(inst, event_desc, group_notify, game_state_override)
        except (asyncio.TimeoutError, TimeoutError):
            self.ctx.logger.warning("决策超时 (%s)", inst.container_name)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.ctx.logger.exception("决策流水线异常 (%s)", inst.container_name)

    async def _decision_flow(self, inst: Instance, event_desc: str,
                             group_notify: bool, game_state_override: dict | None) -> None:
        async with inst.lock:
            # 1. 游戏状态
            bot = BotClient(inst.bot_http_port, timeout=30)
            game_state = game_state_override
            if game_state is None:
                res = await bot.status()
                if res.get("ok"):
                    game_state = self._try_parse_json(res.get("result"))
            game_state_text = self._format_game_state(game_state)

            # 2. 提示词注入：系统提示词 + 游戏状态 + 事件 + 群聊上下文
            system = SYSTEM_PROMPT.format(
                username=inst.username,
                actions_doc=ACTIONS_DOC,
                game_state=game_state_text,
                event_desc=event_desc,
                group_context=inst.readable_context(self.config.context.max_context_messages),
            )
            user = f"当前时间 {now_str()}。事件：{event_desc}\n请给出 JSON 决策。"

            # 3. 调 DeepSeek（带重试与降级）
            try:
                decision = await decide_with_retry(self.llm, system, user, retries=2,
                                                   fallback_actions=[{"cmd": "stop", "args": {}}])
            except LLMError as e:
                self.ctx.logger.error("LLM 决策失败: %s", e)
                return
            except Exception:
                self.ctx.logger.exception("LLM 决策异常")
                return

            thinking = str(decision.get("thinking") or "").strip()
            say_in_game = str(decision.get("say_in_game") or "").strip()
            actions = decision.get("actions") if isinstance(decision.get("actions"), list) else []
            report = str(decision.get("report") or "").strip()
            self.ctx.logger.info("决策[%s] thinking=%s actions=%s", inst.container_name,
                                 truncate(thinking, 80), [a.get("cmd") for a in actions if isinstance(a, dict)])

            # 4. 执行动作（say_in_game 优先）
            results = []
            if say_in_game and not any(isinstance(a, dict) and a.get("cmd") in ("say",) for a in actions):
                results.append({"cmd": "say", **await bot.command("say", {"message": say_in_game})})
            results.extend(await bot.execute_actions(actions))

            # 5. 决策结果反馈到群聊（P1）
            if group_notify and self.config.planner.feedback_to_chat:
                ok_cmds = [r["cmd"] for r in results if r.get("ok")]
                fail_cmds = [r["cmd"] for r in results if not r.get("ok")]
                parts = []
                if report:
                    parts.append(report)
                if ok_cmds:
                    parts.append("（已执行: " + ", ".join(ok_cmds) + "）")
                if fail_cmds:
                    parts.append("（失败: " + ", ".join(fail_cmds) + "）")
                if parts:
                    await self._send_group(inst, f"🤖 {inst.username}: " + " ".join(parts))

            # 6. 触发 maisaka planner（让主程序人格知情/参与）
            summary = report or say_in_game or (f"执行了动作: {', '.join(a['cmd'] for a in results)}" if results else "无动作")
            await self._trigger_maisaka(inst, f"MC 机器人事件：{event_desc}；决策结果：{truncate(summary, 150)}")

    @staticmethod
    def _try_parse_json(text: str) -> dict | None:
        import json
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, ValueError, TypeError):
            return None

    @staticmethod
    def _format_game_state(state: dict | None) -> str:
        if not state:
            return "（暂时无法获取游戏状态，请谨慎行动，先 say 询问或 stop 观望）"
        pos = state.get("pos") or {}
        hp = state.get("hp", state.get("health", "?"))
        food = state.get("food", state.get("food_points", "?"))
        lines = [f"位置: {pos.get('x', '?')}, {pos.get('y', '?')}, {pos.get('z', '?')}"]
        if state.get("dimension"):
            lines.append(f"维度: {state['dimension']}")
        if state.get("time_of_day") is not None or state.get("is_night") is not None:
            lines.append(f"时间: {state.get('time_of_day', '?')} ({'夜晚' if state.get('is_night') else '白天'})")
        lines.append(f"血量: {hp}/20  饥饿度: {food}/20")
        if state.get("held_item"):
            lines.append(f"手持: {state['held_item']}")
        nearby = state.get("nearby_entities")
        if nearby:
            lines.append(f"附近实体: {nearby}")
        inventory = state.get("inventory_summary")
        if inventory:
            lines.append(f"背包概要: {inventory}")
        return "\n".join(lines)

    # ---------- maisaka 联动 ----------

    async def _trigger_maisaka(self, inst: Instance, reason: str) -> None:
        if not self.config.planner.trigger_maisaka:
            return
        try:
            await asyncio.wait_for(
                self.ctx.call_capability(
                    "maisaka.context.append",
                    stream_id=inst.stream_id,
                    segments=[{"type": "text", "content": truncate(reason, 200)}],
                    visible_text=truncate(reason, 200),
                    source_kind="plugin_event",
                ),
                timeout=10,
            )
        except Exception:
            pass  # append 失败不阻塞
        try:
            await asyncio.wait_for(
                self.ctx.call_capability(
                    "maisaka.proactive.trigger",
                    stream_id=inst.stream_id,
                    intent="mc_agent_event",
                    reason=truncate(reason, 200),
                    priority="low",
                    metadata={"plugin": "dzy.mc-agent", "container": inst.container_name},
                ),
                timeout=10,
            )
        except Exception:
            self.ctx.logger.debug("maisaka planner 触发失败（可忽略）")

    # ---------- 消息与历史 ----------

    async def _send_group(self, inst: Instance, text: str) -> None:
        try:
            await self.ctx.send.text(text, inst.stream_id)
        except Exception:
            self.ctx.logger.exception("发送群聊消息失败 (%s)", inst.stream_id)

    async def _fetch_chat_history(self, stream_id: str) -> str:
        """从主程序拉取群聊最近历史（启动时的初始记忆）。"""
        try:
            msgs = await asyncio.wait_for(
                self.ctx.message.get_recent(stream_id, limit=self.config.context.history_limit),
                timeout=15,
            )
            if not msgs:
                return ""
            readable = await asyncio.wait_for(
                self.ctx.message.build_readable(msgs), timeout=15
            )
            if isinstance(readable, dict):
                readable = readable.get("text") or readable.get("content") or ""
            return str(readable or "")
        except Exception:
            self.ctx.logger.debug("拉取群聊历史失败（可忽略）", exc_info=True)
            return ""

    # ---------- 内存监控 ----------

    async def _monitor_loop(self) -> None:
        cfg = self.config.monitor
        while True:
            try:
                await asyncio.sleep(cfg.interval)
                stats = await self.docker.stats_all()
                for s in stats:
                    if s["usage_mb"] is None:
                        continue
                    self.ctx.logger.info(
                        "内存监控 %s: %.0fMB / %.0fMB (%.1f%%)",
                        s["name"], s["usage_mb"], s["limit_mb"] or 1536, s["percent"] or 0,
                    )
                    if s["usage_mb"] > cfg.alert_threshold_mb:
                        inst = self.registry.get_by_container(s["name"])
                        if inst and time.time() - inst.last_alert_ts > cfg.alert_cooldown:
                            inst.last_alert_ts = time.time()
                            await self._send_group(
                                inst,
                                f"⚠️ 容器 {s['name']} 内存已达 {s['usage_mb']:.0f}MB（阈值 {cfg.alert_threshold_mb:.0f}MB，上限 1.5GB），请注意观察。",
                            )
            except asyncio.CancelledError:
                raise
            except Exception:
                self.ctx.logger.exception("内存监控循环异常")


def create_plugin() -> MCAgentPlugin:
    """runner 加载入口（必需）。"""
    return MCAgentPlugin()
