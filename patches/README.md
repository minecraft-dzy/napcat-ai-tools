# 主程序补丁

以下文件是 MaiBot 主程序修改后的版本，覆盖原文件即可。建议先备份原文件。

| 文件 | 路径 | 作用 | 重要程度 |
|---|---|---|---|
| `reasoning_engine.py` | `src/maisaka/` | 1) reply 发送后强制结束循环防止重复回复 2) outbound_send 消息也标记 is_self_message | 强烈推荐 |
| `runtime.py` | `src/maisaka/` | outbound_send 消息标记 is_self_message | 强烈推荐 |
| `context.py` | `src/maisaka/builtin_tool/` | outbound_send 消息标记 is_self_message | 强烈推荐 |
| `query_jargon.py` | `src/maisaka/builtin_tool/` | 同参数重复调用拦截，防止死循环 | 强烈推荐 |
| `query_memory.py` | `src/maisaka/builtin_tool/` | 同参数重复调用拦截，防止死循环 | 强烈推荐 |
| `tool_search.py` | `src/maisaka/builtin_tool/` | 关键词搜不到时用 AI 语义搜索兜底 | 强烈推荐 |
| `maisaka_generator_base.py` | `src/chat/replyer/` | replyer 能看到工具调用结果，避免幻觉 | 强烈推荐 |
| `maisaka_chat.prompt` | `prompts/zh-CN/` | 加入"不回复自己消息"的规则 | 推荐 |

## 安装方式

```bash
# 从 repo 根目录
cp -r patches/src/* /path/to/MaiBot/src/
cp -r patches/prompts/* /path/to/MaiBot/prompts/
```

## 不装补丁的影响

- **replyer 幻觉**：麦麦可能编造数字（工具返回 5 人，说 12 人）
- **重复回复**：可能对同一条消息连发十几条
- **自言自语**：可能回复自己发出的消息
- **死循环**：query_jargon / query_memory 反复查同一词条
- **工具搜不到**：'检查链接安全' 这种自然语言搜不到工具
