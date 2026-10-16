"""通用工具函数。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def truncate(text: str, limit: int = 200) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def extract_json_object(text: str) -> dict[str, Any] | None:
    """从 LLM 回复中尽力提取第一个 JSON 对象。

    兼容 markdown 代码块包裹、前后夹杂说明文字等情况。
    """
    if not text:
        return None
    # 1) 直接解析
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    # 2) ```json ... ``` 代码块
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            continue
    # 3) 第一个 { 到最后一个 } 之间
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            pass
    # 4) 平衡扫描第一个完整对象
    depth, in_str, esc = 0, False, False
    start = text.find("{")
    if start == -1:
        return None
    for i, ch in enumerate(text[start:], start):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start : i + 1])
                    if isinstance(obj, dict):
                        return obj
                except (json.JSONDecodeError, ValueError):
                    return None
    return None


def parse_event_reason(reason_json: str) -> str:
    """把 MC kicked 事件的 reason（JSON 或纯文本）转成可读文本。"""
    if not reason_json:
        return "未知原因"
    try:
        data = json.loads(reason_json)
        if isinstance(data, dict):
            if "translate" in data:
                extra = data.get("with") or []
                extras = ", ".join(
                    x.get("text", "") if isinstance(x, dict) else str(x) for x in extra
                )
                return f"{data['translate']} {extras}".strip()
            if "text" in data:
                return str(data["text"])
        return str(data)
    except (json.JSONDecodeError, ValueError):
        return truncate(str(reason_json), 120)
