# MaiBot 主程序补丁（v1.9.0）

本目录存放 napcat-ai-tools / mc_agent 配套的 MaiBot 主程序修改版文件，适配 **MaiBot v1.0.4**。

补丁主要解决两类问题：

1. **外部 planner 任务支持**（核心）：给主程序加上 `maisaka.external.task` 能力和
   `runtime.run_external_task()` 接口，让插件（如群投票达标后的约定操作）能以完整上下文
   和工具链拉起一次独立的 planner 处理流程，并把结果同步返回给插件。
2. **主程序自身缺陷修复**：防重复回复、防回复自己的消息、防 replyer 幻觉、防工具调用死循环、
   工具语义搜索兜底。

## 补丁清单

| 文件 | 目标路径 | 作用 | 重要程度 |
|---|---|---|---|
| `src/maisaka/runtime.py` | `src/maisaka/` | **新增 `run_external_task()` 外部任务接口（插件触发外部 planner 的核心）** + 外部任务互斥锁 | 必须（外部 planner 功能依赖） |
| `src/plugin_runtime/capabilities/core.py` | `src/plugin_runtime/capabilities/` | `maisaka.external.task` 能力实现（`_cap_maisaka_external_task`） | 必须（外部 planner 功能依赖） |
| `src/plugin_runtime/capabilities/registry.py` | `src/plugin_runtime/capabilities/` | 能力注册表加入 `maisaka.external.task` | 必须（外部 planner 功能依赖） |
| `src/maisaka/reasoning_engine.py` | `src/maisaka/` | reply 发送后强制结束循环防重复回复；outbound_send 消息标记 is_self_message | 强烈推荐 |
| `src/maisaka/builtin_tool/context.py` | `src/maisaka/builtin_tool/` | outbound_send 消息标记 is_self_message | 强烈推荐 |
| `src/maisaka/builtin_tool/query_jargon.py` | `src/maisaka/builtin_tool/` | 同参数重复调用拦截，防止死循环 | 强烈推荐 |
| `src/maisaka/builtin_tool/query_memory.py` | `src/maisaka/builtin_tool/` | 同参数重复调用拦截，防止死循环 | 强烈推荐 |
| `src/maisaka/builtin_tool/tool_search.py` | `src/maisaka/builtin_tool/` | 关键词搜不到时用 AI 语义搜索兜底 | 强烈推荐 |
| `src/chat/replyer/maisaka_generator_base.py` | `src/chat/replyer/` | replyer 能看到工具调用结果，避免幻觉 | 强烈推荐 |
| `prompts/zh-CN/maisaka_chat.prompt` | `prompts/zh-CN/` | 加入"不回复自己消息"等规则 + napcat 工具使用规则 | 推荐 |

## 推荐安装方式：补丁安装工具

`patch_tool.py` 会自动完成 **检测 → 跳过/备份 → 安装 → 校验 →（失败）回滚**：

```bash
cd patches/

# 查看补丁状态（已装 / 未装 / 被外部改过）
python patch_tool.py status --target /path/to/MaiBot

# 安装补丁
#   - 已安装的自动跳过（可重复执行，幂等）
#   - 覆盖前自动把原文件备份到 <MaiBot>/patches_backup/<时间戳>/
#   - 任一步失败自动回滚本次全部改动，恢复到安装前状态
python patch_tool.py install --target /path/to/MaiBot

# 卸载补丁（从备份还原原文件）
python patch_tool.py uninstall --target /path/to/MaiBot
```

`--target` 指向 MaiBot 主程序根目录（即包含 `src/` 与 `prompts/` 的目录，上例为 `/home`）；
也可以用环境变量 `MAIBOT_HOME` 指定。安装完成后重启 MaiBot 生效。

状态记录写在 `<MaiBot根目录>/.napcat-ai-tools-patches.json`，`status` / `uninstall` 都依赖它；
就算没有状态文件，`install` 也能通过文件哈希识别出已装补丁并跳过，同时补写状态文件。

## 手动安装（不推荐，无备份无回滚）

```bash
# 在仓库根目录
cp -r patches/src/* /path/to/MaiBot/src/
cp -r patches/prompts/* /path/to/MaiBot/prompts/
```

## 不装补丁的影响

- **外部 planner 不可用**：插件调用 `maisaka.external.task` 会失败（群投票达标后的约定操作等功能依赖它）
- **replyer 幻觉**：麦麦可能编造数字（工具返回 5 人，说 12 人）
- **重复回复**：可能对同一条消息连发十几条
- **自言自语**：可能回复自己发出的消息
- **死循环**：query_jargon / query_memory 反复查同一词条
- **工具搜不到**：'检查链接安全' 这种自然语言搜不到工具

## 注意事项

- 补丁基于 **MaiBot v1.0.4** 的源文件修改，主程序升级后需要重新核对
- 覆盖的是整文件而非 diff，如果主程序对应文件有过其他自定义修改，会被覆盖
 （`install` 检测到这种情况会跳过并提示，加 `--force` 才会强制覆盖）
- 备份目录 `patches_backup/` 在卸载确认无误后可以手动删除
