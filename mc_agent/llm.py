"""LLM 交互模块：DeepSeek 决策与自然语言生成。

支持两种模式：
- host:   经 MaiBot 主程序 self.ctx.llm.generate（服务器已配置 DeepSeek 模型）
- direct: 直连 DeepSeek OpenAI 兼容 API（config [llm] api_key）
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import aiohttp

from utils.helpers import extract_json_object

# 决策提示词中可用的游戏动作（与 mc_client/bot.js 的命令一一对应）
ACTIONS_DOC = """可用动作（actions 数组，每项 {"cmd": 名称, "args": 参数}）：
- say        {"message": "游戏内说的话"}          在游戏内聊天
- goto       {"x": 0, "y": 64, "z": 0}            走到坐标附近
- come       {"player": "玩家名", "range": 2}      走到某玩家身边
- follow     {"player": "玩家名"}                  跟随玩家
- unfollow   {}                                    停止跟随
- collect    {"block": "钻石矿|log|stone等", "count": 1}  寻找并采集方块
- dig        {"x": 0, "y": 64, "z": 0}             挖掉指定坐标方块
- craft      {"item": "物品英文ID如 crafting_table", "count": 1} 合成物品
- attack     {"target": "玩家名或怪物名", "radius": 8}    攻击最近匹配实体
- eat        {}                                    进食（自动选背包食物）
- equip_best {}                                    穿戴最好的装备
- list_inventory {}                                查看背包（结果会在下轮提供）
- drop       {"item": "物品ID", "count": 1}        丢弃物品
- look       {"player": "玩家名"}                  看向玩家
- stop       {}                                    停止当前一切动作

回复必须是一个 JSON 对象（不要输出其他文字）：
{
  "thinking": "简短内心想法",
  "say_in_game": "要在游戏内说的话，没有就留空",
  "actions": [{"cmd": "...", "args": {...}}],
  "report": "要回报到群聊的一句话，没有就留空"
}"""

SYSTEM_PROMPT = """你是一个 Minecraft 原版生存服务器上的真人玩家，游戏昵称 {username}。你同时在一个 QQ 群里和群友们聊天。

行为准则：
1. 像真人一样生存：注意血量和饥饿度，饿了要吃（eat），天黑远离怪物或战斗，低血量优先保命。
2. 像真人一样说话：游戏内发言和群聊发言都要口语化、简短、符合中文聊天习惯，不要长篇大论，不要自称 AI。
3. 谨慎行动：一次决策只安排少量动作（1~3 个），不要频繁跑图刷屏，遵守服务器规则。
4. 事件响应：被踢出/死亡/受伤/捡到稀有物品时，先判断情况再决定动作。
5. 你能看到群聊上下文，如果群友在游戏里指派你做事（挖矿、过来、打架等），尽量照做。

{actions_doc}

当前游戏状态：
{game_state}

发生的事件：
{event_desc}

最近群聊上下文（供你了解大家在聊什么）：
{group_context}"""


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self, ctx: Any, cfg: Any, logger=None) -> None:
        self.ctx = ctx  # PluginContext
        self.cfg = cfg  # llm 配置节
        self.log = logger

    async def chat(self, system: str, user: str, history: list[dict] | None = None) -> str:
        """发起一次对话，返回文本。失败抛 LLMError。"""
        if self.cfg.mode == "direct" and self.cfg.api_key:
            return await self._chat_direct(system, user, history)
        return await self._chat_host(system, user, history)

    async def decide(self, system: str, user: str) -> Optional[dict[str, Any]]:
        """对话并解析决策 JSON，失败返回 None。"""
        text = await self.chat(system, user)
        data = extract_json_object(text)
        if data is None:
            (self.log or __import__("logging").getLogger(__name__)).warning(
                "LLM 决策 JSON 解析失败: %s", text[:200]
            )
        return data

    async def _chat_host(self, system: str, user: str, history: list[dict] | None = None) -> str:
        messages: list[dict] = [{"role": "system", "content": system}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user})
        try:
            result = await asyncio.wait_for(
                self.ctx.llm.generate(prompt=messages, model=self.cfg.host_model,
                                      max_tokens=self.cfg.max_tokens),
                timeout=self.cfg.timeout,
            )
        except asyncio.TimeoutError as e:
            raise LLMError(f"host LLM 超时({self.cfg.timeout}s)") from e
        except Exception as e:  # RPC 层错误
            raise LLMError(f"host LLM 调用失败: {e}") from e
        if isinstance(result, dict) and result.get("success") and result.get("response"):
            return str(result["response"])
        raise LLMError(f"host LLM 返回异常: {str(result)[:200]}")

    async def _chat_direct(self, system: str, user: str, history: list[dict] | None = None) -> str:
        base = self.cfg.base_url.rstrip("/")
        # 兼容 DeepSeek2（base 无 /v1）与旧版 OpenAI 兼容地址
        if not base.endswith("/v1"):
            base += "/v1"
        url = base + "/chat/completions"
        messages: list[dict] = [{"role": "system", "content": system}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user})
        payload = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens,
        }
        headers = {"Authorization": f"Bearer {self.cfg.api_key}"}
        try:
            timeout = aiohttp.ClientTimeout(total=self.cfg.timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise LLMError(f"DeepSeek API {resp.status}: {body[:200]}")
                    data = await resp.json()
        except asyncio.TimeoutError as e:
            raise LLMError("DeepSeek API 超时") from e
        except aiohttp.ClientError as e:
            raise LLMError(f"DeepSeek API 网络错误: {e}") from e
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"DeepSeek API 响应格式异常: {e}") from e


async def decide_with_retry(
    llm: LLMClient, system: str, user: str, retries: int = 2, fallback_actions: list[dict] | None = None
) -> dict[str, Any]:
    """带重试的决策；全部失败时降级到预设动作。"""
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            decision = await llm.decide(system, user)
            if decision is not None:
                return decision
            last_err = LLMError("决策 JSON 解析失败")
        except LLMError as e:
            last_err = e
        if attempt < retries:
            await asyncio.sleep(3 * (attempt + 1))
    actions = fallback_actions or [{"cmd": "stop", "args": {}}]
    return {
        "thinking": f"LLM 决策失败({last_err})，降级预设动作",
        "say_in_game": "",
        "actions": actions,
        "report": "",
    }
