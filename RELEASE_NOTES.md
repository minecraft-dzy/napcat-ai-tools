# v1.9.2 - 启动补丁提醒选择框 / 关闭工具不再加载 ⚠️ 不稳定版本

> 本版本标注为 **不稳定（Pre-release）**，无新增工具，聚焦补丁体验与 planner token 优化。

## 主程序补丁新增

- **启动补丁提醒选择框**（新增 `integration.py` 补丁）：主程序启动加载插件前检查补丁状态，有补丁缺失或被外部改动时在终端用字符打印彩色选择框
  - 选项：**不再提醒 / 立即安装 / 取消**，方向键（↑/↓/k/j）或数字键移动，Enter 确认，Esc/Ctrl+C 取消
  - **10 秒无按键自动视为取消**，不影响正常启动
  - 无键盘输入的终端（非 TTY）自动降级为一行提示，不弹框不阻塞
  - 选「立即安装」直接调用暂存在 `<MaiBot>/patches_tool/` 的补丁载荷离线完成安装，无需仓库和网络
  - 补丁齐全或选过「不再提醒」时静默通过；补丁出现新漂移会重新提醒
- `patch_tool.py install` 成功后自动把整套补丁文件与 patch_tool.py 暂存到 `<MaiBot>/patches_tool/`，供启动选择框离线修复使用

## 插件改进

- **插件设置里关闭的工具，重启后直接不加载**：`get_components()` 注册阶段即过滤掉开关为 False 的 TOOL 类型组件，planner 完全看不到这些工具，**不再占用 planner 输入 token**（Hook / Command / EventHandler 等其他组件类型不受影响）
- 补全配置模型缺失的 `check_mute_status` 开关字段（v1.9.0 遗留）

## 升级说明

1. 覆盖插件目录后热重载自动生效（改过 `_manifest.json` 需重启主程序）
2. 重新执行 `patches/patch_tool.py install`（已装其他补丁的会增量安装新的 integration.py 补丁）
3. 想要启动提醒功能必须安装 `integration.py` 补丁（`patch_tool.py status` 可查看）

---

# v1.9.0 - 群投票 / MC 服务器管理 / 收藏夹 / 外部 planner 补丁 ⚠️ 不稳定版本

> 本版本标注为 **不稳定（Pre-release）**：涉及外部 planner 补丁与较多新功能，建议先在测试环境验证。

## 新增工具（16 个，总计 106 个）

| 工具名 | 说明 |
|---|---|
| `group_vote` | 群投票：发布投票消息并贴 👍 计票，达标后自动执行约定操作（如解禁），并通过 `maisaka.external.task` 拉起 planner 处理；投票状态持久化，插件重载后自动恢复 |
| `napcat_add_favorite` | 收藏消息到麦麦全局收藏夹（所有会话共享） |
| `napcat_list_favorites` | 查看全局收藏夹列表 |
| `napcat_send_favorites` | 把收藏合并转发到群里展示 |
| `napcat_check_mute_status` | 检查群成员是否被禁言及剩余秒数 |
| `napcat_infinite_ban` | 无限禁言：循环续禁防止他人解封 |
| `napcat_stop_infinite_ban` | 停止无限禁言循环 |
| `mc_server_status` | 查看 MC 服务运行状态（Java 进程 / 25565 端口） |
| `mc_server_start` | 启动 Minecraft 服务端 |
| `mc_server_stop` | 停止 Minecraft 服务端 |
| `mc_server_deploy` | 获取 MC 部署指引 |
| `mc_remote_view_file` | 查看 MC 机器工作目录文件 |
| `mc_remote_create_file` | 在 MC 机器工作目录创建文件 |
| `mc_remote_modify_file` | 修改 MC 机器工作目录文件 |
| `mc_remote_upload_file` | 上传服务器文件到 MC 机器 |
| `mc_remote_exec` | 在 MC 机器执行 Windows 命令 |

## 功能改进

- **MC 服务器远程管理**：通过 SSH 管理本地 MC 机器（`[minecraft_server]` 配置区），AI 可自助部署/启停/运维 Minecraft 服务端
- **公网代理服务器**：新增 `proxy_server.py`（FastAPI），为无公网环境提供请求转发、投票/求情数据中转（`[proxy]` / `[plea]` / `[update]` / `[log]` 配置区）
- **撤职守卫**（`napcat_demotion_guard` 钩子）：管理员身份被撤销后自动拦截后续消息处理，恢复身份后自动解除
- **CosyVoice2 语音**：`napcat_send_cosyvoice_record` 支持情绪朗读（v1.8.0 引入，本版继续优化）
- 新增 capabilities 声明：`chat.get_stream_by_group_id`、`maisaka.external.task`

## 主程序补丁（重要）

`patches/` 目录随本版更新，并新增补丁安装工具 `patch_tool.py`：

- **外部 planner 任务支持**：`runtime.py` 新增 `run_external_task()` 接口，`plugin_runtime/capabilities` 注册 `maisaka.external.task` 能力 —— 插件可以拉起一次独立的 planner 处理流程（群投票达标后执行约定操作依赖此补丁）
- 补丁安装工具特性：
  - 已安装自动检测并跳过（幂等，可重复执行）
  - 覆盖前自动备份原文件到 `<MaiBot>/patches_backup/<时间戳>/`
  - 任一步失败自动回滚全部改动，恢复安装前状态
  - 支持 `status` / `install` / `uninstall` 子命令

```bash
cd patches/
python patch_tool.py install --target /path/to/MaiBot   # 安装（已装自动跳过）
python patch_tool.py status  --target /path/to/MaiBot   # 查看状态
python patch_tool.py uninstall --target /path/to/MaiBot # 卸载还原
```

## 本仓库新增内容

- 收录 **mc_agent v1.0.0** 插件源码（Minecraft 智能体：Mineflayer 无头客户端 + Docker 隔离 + DeepSeek 决策，详见 `mc_agent/`）
- 同步 v1.9.0 插件完整源码（`plugin.py` / `proxy_server.py` 等）

## 升级说明

1. 覆盖插件目录后热重载自动生效（改过 `_manifest.json` 需重启主程序）
2. 重新执行 `patches/patch_tool.py install`（已装会自动跳过）
3. 仓库内 `config.toml` 中的密钥字段已清空，请通过 WebUI 配置面板填写

---

# v0.3.0 - @人功能

## 新增工具

| 工具名 | 说明 |
|---|---|
| `napcat_at_user` | 在群聊中 @指定用户并发送消息，对方会收到真正的 @通知提醒 |

## 功能改进

- @功能使用 NapCat 原生 `send_msg` API + OneBot v11 `at` 消息段，确保真正的 QQ @提醒
- 支持按 QQ 号精确 @，也支持按昵称/群名片模糊搜索目标用户
- 提示词优化：引导 AI 在群聊中优先使用 @工具而非普通 reply

### 依赖
- 无需修改主程序代码，纯插件即可使用

---

# v0.2.0

## 修复

- **命令授权 QQ**：从写死 `3939129639` 改为配置项 `command_confirm_qq`，在 WebUI「安全」分区填写
- **manifest 补齐**：新增 `host_application.max_version` 和 `sdk.max_version`，修复插件校验失败
- 重命名 `napcat_ai_tools.py` → `plugin.py`，目录可直接作为标准 MaiBot 插件加载

---

# v0.1.0 - 首个发布版本

80+ 个 NapCat 工具，覆盖群管理、好友管理、消息操作、系统状态、文件执行。

## 工具列表

### 群信息（14 个）

| 工具名 | 说明 |
|---|---|
| `napcat_list_groups` | 获取群聊列表 |
| `napcat_get_group_info` | 获取群信息 |
| `napcat_list_group_members` | 获取群成员列表 |
| `napcat_get_group_admins` | 获取管理员列表 |
| `napcat_get_group_member_info` | 获取成员资料与权限 |
| `napcat_get_self_role` | 查自己在群里的角色（owner/admin/member） |
| `napcat_get_group_member_moderation_status` | 检查禁言状态 |
| `napcat_list_group_banned_members` | 获取禁言名单 |
| `napcat_get_group_notices` | 获取群公告列表 |
| `napcat_list_group_requests` | 查看群申请/邀请记录 |
| `napcat_get_group_at_all_remain` | @全体剩余次数 |
| `napcat_list_group_essence_messages` | 精华消息 |
| `napcat_get_group_honor_info` | 群荣誉信息 |
| `napcat_check_group_join_status` | 检查是否已入群 |

### 群管理（21 个）

| 工具名 | 说明 | 风险 |
|---|---|---|
| `napcat_set_group_ban` | 禁言成员 | 高 |
| `napcat_kick_group_member` | 踢出成员 | 高 |
| `napcat_set_group_admin` | 设置管理员 | 高 |
| `napcat_set_group_whole_ban` | 全员禁言 | 高 |
| `napcat_leave_group` | 退群/解散群 | 高 |
| `napcat_set_group_add_option` | 设置入群方式 | 中 |
| `napcat_send_group_notice` | 发群公告 | 中 |
| `napcat_set_group_name` | 修改群名称 | 中 |
| `napcat_set_group_portrait` | 设置群头像 | 中 |
| `napcat_set_group_remark` | 设置群备注 | 低 |
| `napcat_set_group_card` | 设置群名片 | 低 |
| `napcat_set_group_special_title` | 设置专属头衔 | 低 |
| `napcat_send_group_sign` | 群打卡 | 低 |
| `napcat_set_group_todo` | 创建群待办 | 低 |
| `napcat_handle_group_request` | 处理加群请求 | 中 |
| `napcat_delete_group_notice` | 删除群公告 | 中 |
| `napcat_set_essence_message` | 设为精华消息 | 低 |
| `napcat_delete_essence_message` | 取消精华 | 低 |
| `napcat_send_poke` | 发送戳一戳 | 低 |
| `napcat_watch_group_join_status` | 登记进群观察 | 低 |
| `napcat_remove_group_join_watch` | 删除进群观察 | 低 |

### 好友与申请（11 个）

| 工具名 | 说明 |
|---|---|
| `napcat_list_friends` | 好友列表 |
| `napcat_list_unidirectional_friends` | 单向好友列表 |
| `napcat_get_user_profile` | 获取 QQ 资料 |
| `napcat_list_recent_contacts` | 最近会话列表 |
| `napcat_delete_friend` | 删除好友 |
| `napcat_set_friend_remark` | 设置好友备注 |
| `napcat_list_pending_friend_requests` | 待处理好友申请 |
| `napcat_handle_friend_request` | 处理好友申请 |
| `napcat_list_doubt_friend_requests` | 可疑好友申请 |
| `napcat_handle_doubt_friend_request` | 处理可疑申请 |
| `napcat_send_like` | 资料卡点赞 |

### 消息与表情（15 个）

| 工具名 | 说明 |
|---|---|
| `napcat_delete_message` | 撤回消息 |
| `napcat_get_forward_message` | 查看合并转发消息 |
| `napcat_send_forward_message` | 发送合并转发消息 |
| `napcat_forward_friend_single_msg` | 转发消息到好友 |
| `napcat_forward_group_single_msg` | 转发消息到群 |
| `napcat_get_friend_msg_history` | 拉取好友历史消息 |
| `napcat_get_group_msg_history` | 拉取群历史消息 |
| `napcat_mark_all_as_read` | 标记所有消息已读 |
| `napcat_mark_group_as_read` | 标记群聊已读 |
| `napcat_mark_private_as_read` | 标记私聊已读 |
| `napcat_get_message_detail` | 获取消息详情 |
| `napcat_set_message_emoji_like` | 给消息贴表情 |
| `napcat_get_message_emoji_likes` | 查看表情回应列表 |
| `napcat_fetch_message_emoji_like_detail` | 表情回应详情分页 |
| `napcat_ocr_image` | 图片 OCR 文字识别 |

### 系统与状态（10 个）

| 工具名 | 说明 |
|---|---|
| `napcat_get_login_info` | 获取登录 QQ 信息 |
| `napcat_raw_action` | 调用原始 NapCat 动作 |
| `napcat_check_url_safely` | 检查链接安全性 |
| `napcat_url_safety_check` | 链接安全检查（总是安全） |
| `napcat_can_send_image` | 检查能否发图片 |
| `napcat_can_send_record` | 检查能否发语音 |
| `napcat_get_status` | 获取 NapCat 运行状态 |
| `napcat_get_version_info` | 获取版本信息 |
| `napcat_get_online_clients` | 获取在线客户端 |
| `napcat_get_user_online_status` | 获取用户在线状态 |

### 资料与 AI（4 个）

| 工具名 | 说明 |
|---|---|
| `napcat_set_self_profile` | 修改自己的昵称、签名、性别 |
| `napcat_set_self_longnick` | 设置长个性签名 |
| `napcat_list_ai_characters` | 获取 AI 语音角色列表 |
| `napcat_send_group_ai_record` | 发送群 AI 语音 |

### 文件与执行（6 个）

| 工具名 | 说明 |
|---|---|
| `napcat_download_file` | 从 URL 下载文件 |
| `napcat_download_qq_file` | 通过 NapCat 下载 QQ 文件 |
| `napcat_view_file` | 查看本地文件内容 |
| `napcat_extract_file` | 解压压缩文件 |
| `napcat_fetch_webpage` | 获取网页 HTML |
| `napcat_execute_command` | 执行命令（需授权确认） |

## 修复

- **命令授权 QQ**：从写死 `3939129639` 改为配置项 `command_confirm_qq`，在 WebUI「安全」分区填写
- **manifest 补齐**：新增 `host_application.max_version` 和 `sdk.max_version`，修复插件校验失败
- 重命名 `napcat_ai_tools.py` → `plugin.py`，目录可直接作为标准 MaiBot 插件加载

## 主程序补丁（patches/）

以下补丁修复 MaiBot 本身的缺陷，需手动覆盖到 `src/` 和 `prompts/`：

| 文件 | 作用 |
|---|---|
| `reasoning_engine.py` | reply 后强制结束循环，防止对同一条消息重复回复十几次 |
| `runtime.py` | `outbound_send` 消息标记 `is_self_message`，避免回复自己的消息 |
| `builtin_tool/context.py` | `is_self_message` 标记 |
| `builtin_tool/query_jargon.py` | 相同参数重复调用拦截，防止死循环 |
| `builtin_tool/query_memory.py` | 相同参数重复调用拦截，防止死循环 |
| `builtin_tool/tool_search.py` | 关键词搜不到工具时用 AI 语义搜索兜底 |
| `chat/replyer/maisaka_generator_base.py` | replyer 能看到工具调用结果，避免编造数据幻觉 |
| `prompts/zh-CN/maisaka_chat.prompt` | 加入"不回复自己消息、不自言自语"规则 |
