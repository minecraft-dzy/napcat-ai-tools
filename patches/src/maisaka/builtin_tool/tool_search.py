"""tool_search 内置工具。"""

from typing import Any, Dict, List, Optional

from src.core.tooling import ToolExecutionContext, ToolExecutionResult, ToolInvocation, ToolSpec

from .context import BuiltinToolRuntimeContext


def get_tool_spec() -> ToolSpec:
    """获取 tool_search 工具声明。"""

    return ToolSpec(
        name="tool_search",
        description="在 deferred tools 列表中按名称或关键词搜索工具，并将命中的工具加入后续轮次的可用工具列表。支持语义搜索，可以用自然语言描述你想找什么工具（如'访问网页的工具'、'发群公告的工具'、'检查链接是否安全'等）。若结果显示某工具此前已发现，下一步应直接调用该业务工具，不要重复 tool_search。",
        parameters_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "要搜索的工具名、前缀或关键词，也可以用自然语言描述想找什么功能的工具。",
                },
                "limit": {
                    "type": "integer",
                    "description": "最多返回多少个匹配工具。",
                    "minimum": 1,
                },
            },
            "required": ["query"],
        },
        provider_name="maisaka_builtin",
        provider_type="builtin",
    )


async def handle_tool(
    tool_ctx: BuiltinToolRuntimeContext,
    invocation: ToolInvocation,
    context: Optional[ToolExecutionContext] = None,
) -> ToolExecutionResult:
    """执行 tool_search 内置工具。"""

    del context
    raw_query = invocation.arguments.get("query")
    if not isinstance(raw_query, str) or not raw_query.strip():
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            "tool_search 需要提供非空的 `query` 字符串参数。",
        )

    raw_limit = invocation.arguments.get("limit", 5)
    try:
        limit = max(1, int(raw_limit))
    except (TypeError, ValueError):
        limit = 5

    matched_tool_specs = tool_ctx.runtime.search_deferred_tool_specs(raw_query, limit=limit)
    matched_tool_names = [tool_spec.name for tool_spec in matched_tool_specs]
    newly_discovered_tool_names = tool_ctx.runtime.discover_deferred_tools(matched_tool_names)
    already_discovered_tool_names = [
        tool_name for tool_name in matched_tool_names if tool_name not in set(newly_discovered_tool_names)
    ]

    structured_content: Dict[str, Any] = {
        "query": raw_query.strip(),
        "matched_tool_names": matched_tool_names,
        "newly_discovered_tool_names": newly_discovered_tool_names,
        "already_discovered_tool_names": already_discovered_tool_names,
    }

    if not matched_tool_names:
        # 关键词匹配未命中，尝试 AI 语义搜索
        ai_matched_tool_names = await _ai_search_tools(tool_ctx, raw_query.strip(), limit)
        if ai_matched_tool_names:
            # 将 AI 结果映射回 ToolSpec
            ai_matched_tool_specs = [
                tool_ctx.runtime.deferred_tool_specs_by_name[name]
                for name in ai_matched_tool_names
                if name in tool_ctx.runtime.deferred_tool_specs_by_name
            ]
            if ai_matched_tool_specs:
                matched_tool_specs = ai_matched_tool_specs
                matched_tool_names = [t.name for t in matched_tool_specs]
                newly_discovered_tool_names = tool_ctx.runtime.discover_deferred_tools(matched_tool_names)
                already_discovered_tool_names = [
                    name for name in matched_tool_names if name not in set(newly_discovered_tool_names)
                ]
                structured_content = {
                    "query": raw_query.strip(),
                    "matched_tool_names": matched_tool_names,
                    "newly_discovered_tool_names": newly_discovered_tool_names,
                    "already_discovered_tool_names": already_discovered_tool_names,
                    "ai_search_used": True,
                }

    if not matched_tool_names:
        return tool_ctx.build_success_result(
            invocation.tool_name,
            "未找到匹配的 deferred tools，请尝试更完整的工具名、前缀或其他关键词。",
            structured_content=structured_content,
        )

    newly_discovered_tool_name_set = set(newly_discovered_tool_names)
    content_lines: List[str] = [
        f"已找到 {len(matched_tool_names)} 个 deferred tools，它们会在后续轮次中加入可用工具列表：",
        *[
            (
                f"- {tool_spec.name}"
                f"{'（本次新发现）' if tool_spec.name in newly_discovered_tool_name_set else '（此前已发现）'}"
                f"{'：' + tool_spec.description if tool_spec.description else ''}"
            )
            for tool_spec in matched_tool_specs
        ],
    ]
    if already_discovered_tool_names and not newly_discovered_tool_names:
        if len(already_discovered_tool_names) == 1:
            content_lines.append(
                f"该工具此前已发现，当前不要再次调用 tool_search；下一步请直接调用 `{already_discovered_tool_names[0]}`。"
            )
        else:
            content_lines.append(
                "这些工具此前已发现，当前不要再次调用 tool_search；下一步请直接从上述业务工具中选择合适的一个调用。"
            )
    elif newly_discovered_tool_names:
        if len(matched_tool_names) == 1:
            content_lines.append(f"下一步请直接调用 `{matched_tool_names[0]}`，不要重复 tool_search。")
        else:
            content_lines.append("这些工具已经发现完成；下一步请直接调用合适的业务工具，不要重复 tool_search。")

    return tool_ctx.build_success_result(
        invocation.tool_name,
        "\n".join(content_lines),
        structured_content=structured_content,
        metadata={
            "matched_tool_names": matched_tool_names,
            "newly_discovered_tool_names": newly_discovered_tool_names,
            "already_discovered_tool_names": already_discovered_tool_names,
        },
    )


async def _ai_search_tools(
    tool_ctx: BuiltinToolRuntimeContext,
    query: str,
    limit: int,
) -> list[str]:
    """使用 LLM 进行语义工具搜索，作为关键词匹配的兜底方案。"""

    deferred_tools = tool_ctx.runtime.deferred_tool_specs_by_name
    if not deferred_tools:
        return []

    # 构建工具列表
    tool_lines: list[str] = []
    for tool_name, tool_spec in sorted(deferred_tools.items()):
        desc = (tool_spec.description or "").strip()
        tool_lines.append(f"- {tool_name}: {desc}")

    tool_list_text = "\n".join(tool_lines)
    prompt = (
        "你是一个工具搜索引擎。根据用户的搜索意图，从以下工具列表中找到最匹配的工具。\n"
        "只返回匹配的工具名（精确的 tool name），每行一个，不要返回不存在的工具名。\n"
        "按匹配度从高到低排序。如果没有任何工具匹配，返回空（只返回一个 EMPTY）。\n"
        "不要返回解释、JSON 或其他格式，只返回工具名，每行一个。\n\n"
        f"搜索意图：{query}\n\n"
        f"可用工具列表（名称: 描述）：\n{tool_list_text}\n\n"
        "请返回最匹配的工具名，每行一个（无匹配则返回 EMPTY）："
    )

    try:
        from src.services.llm_service import LLMServiceClient
        from src.common.data_models.llm_service_data_models import LLMGenerationOptions

        llm_client = LLMServiceClient(
            task_name="utils",
            request_type="maisaka.tool_search.ai_fallback",
            session_id=tool_ctx.runtime.session_id,
        )
        response = await llm_client.generate_response(
            prompt,
            options=LLMGenerationOptions(max_tokens=200, temperature=0.1),
        )
        raw_text = (response.response or "").strip()
        if not raw_text or raw_text.upper() == "EMPTY":
            return []

        # 解析返回的工具名（每行一个）
        matched: list[str] = []
        lower_tool_map = {name.lower(): name for name in deferred_tools}
        for line in raw_text.splitlines():
            candidate = line.strip().lower()
            if not candidate or candidate == "empty":
                continue
            if candidate in lower_tool_map:
                matched.append(lower_tool_map[candidate])
        return matched[:max(1, limit)]
    except Exception:
        return []
