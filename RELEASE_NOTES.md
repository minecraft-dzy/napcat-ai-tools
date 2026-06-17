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
