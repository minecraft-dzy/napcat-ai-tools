# napcat-ai-tools

为 [MaiBot](https://github.com/MaiBot-OpenSource) 提供 NapCat QQ 管理工具集，让 AI 能操作群聊、好友、消息、文件等。

当前版本：**v1.9.2**（106 个工具，含群投票、MC 服务器远程管理、收藏夹、禁言求情等；插件设置里关闭的工具重启后直接不加载，不占用 planner token）

> 本仓库同时收录配套的 **mc_agent** 插件（Minecraft 智能体，见下方说明）和 **MaiBot 主程序补丁**（见 `patches/`）。

## 仓库结构

```
├── plugin.py / _manifest.json / config.toml / proxy_server.py   # napcat-ai-tools 插件源码（v1.9.2）
├── napcat-ai-tools/                                             # 同上，可直接拷入 plugins/ 的目录版
├── mc_agent/                                                    # mc_agent 插件（Minecraft 智能体）
├── patches/                                                     # MaiBot 主程序补丁 + 补丁安装工具
└── RELEASE_NOTES.md                                             # 版本说明
```

## 安装

### 1. 放入插件目录

```bash
# 整个目录就是 MaiBot 的一个插件
cp -r napcat-ai-tools /path/to/MaiBot/plugins/
```

### 2. 应用主程序补丁（推荐）

```bash
cd patches/
python patch_tool.py install --target /path/to/MaiBot
```

补丁安装工具会自动完成检测、备份、安装、校验，任一步失败自动回滚；已安装的补丁再次执行会自动跳过。
补丁修了几个 MaiBot 自身的问题（外部 planner 支持、replyer 幻觉、重复回复、死循环、工具搜索太弱），详见 `patches/README.md`。

不装也能用，但群投票达标后拉起 planner 等功能会失效，体验也会差一些。

### 3. 安装依赖

```bash
pip install httpx fastapi uvicorn
```

### 4. 重启 MaiBot

在 WebUI 插件面板中可以看到 "NapCat AI Tools" 分类。

## 配置

所有工具都可在 WebUI 的插件配置面板中单独开关，默认全部启用。

配置文件 `config.toml` 与 WebUI 面板同步，一般不需要手动编辑。

## 工具列表（106 个）

### 群信息（17 个）

| 工具 | 说明 |
|---|---|
| `napcat_list_groups` | 获取群聊列表 |
| `napcat_get_group_info` | 获取群信息 |
| `napcat_list_group_members` | 获取群成员列表 |
| `napcat_get_group_admins` | 获取管理员列表 |
| `napcat_get_group_member_info` | 获取成员资料与权限 |
| `napcat_get_self_role` | 查自己在群里的角色（群主/管理/成员） |
| `napcat_get_group_member_moderation_status` | 检查某成员禁言状态 |
| `napcat_list_group_banned_members` | 获取禁言名单 |
| `napcat_check_mute_status` | 检查成员是否被禁言及剩余秒数 |
| `napcat_get_group_notices` | 获取群公告列表 |
| `napcat_list_group_requests` | 查看群申请或邀请记录 |
| `napcat_get_group_at_all_remain` | 获取 @全体 剩余次数 |
| `napcat_list_group_essence_messages` | 获取精华消息 |
| `napcat_get_group_honor_info` | 获取群荣誉信息 |
| `napcat_check_group_join_status` | 检查是否已入群 |
| `napcat_watch_group_join_status` / `napcat_list_group_join_watches` | 登记并跟踪进群结果 |
| `napcat_get_user_group_context` | 查某 QQ 最近和麦麦有过上下文的群 |

### 群管理（26 个）

| 工具 | 说明 | 风险 |
|---|---|---|
| `napcat_set_group_ban` | 禁言成员 | 高 |
| `napcat_infinite_ban` | 无限禁言（防解封循环） | 高 |
| `napcat_stop_infinite_ban` | 停止无限禁言 | 高 |
| `napcat_kick_group_member` | 踢出成员 | 高 |
| `napcat_set_group_admin` | 设置管理员 | 高 |
| `napcat_set_group_whole_ban` | 全员禁言 | 高 |
| `napcat_leave_group` | 退群/解散群 | 高 |
| `napcat_unmute_user` | 解除成员禁言 | 中 |
| `napcat_set_group_add_option` | 设置入群方式 | 中 |
| `napcat_send_group_notice` | 发群公告 | 中 |
| `napcat_delete_group_notice` | 删除群公告 | 中 |
| `napcat_set_group_name` | 修改群名称 | 中 |
| `napcat_set_group_portrait` | 设置群头像 | 中 |
| `napcat_handle_group_request` | 处理加群请求 | 中 |
| `napcat_set_group_remark` | 设置群备注 | 低 |
| `napcat_set_group_card` | 设置群名片 | 低 |
| `napcat_set_group_special_title` | 设置专属头衔 | 低 |
| `napcat_send_group_sign` | 群打卡 | 低 |
| `napcat_set_group_todo` | 创建群待办 | 低 |
| `napcat_set_essence_message` | 设为精华消息 | 低 |
| `napcat_delete_essence_message` | 取消精华 | 低 |
| `napcat_send_poke` | 发戳一戳 | 低 |
| `napcat_at_user` | @指定用户并发送消息 | 低 |
| `napcat_watch_group_join_status` | 登记进群观察 | 低 |
| `napcat_remove_group_join_watch` | 删除进群观察 | 低 |
| `napcat_approve_plea` | 审核通过禁言求情并解禁 | 中 |

### 求情（3 个）

被禁言的用户可以通过求情流程申请解禁（麦麦审核，`napcat_list_pleas` 查看待审列表）。

| 工具 | 说明 |
|---|---|
| `napcat_list_pleas` | 查看当前待处理的禁言求情列表 |
| `napcat_approve_plea` | 审核通过求情，自动解禁并通知用户 |
| `napcat_unmute_user` | 解除群成员禁言 |

### 好友与申请（11 个）

| 工具 | 说明 |
|---|---|
| `napcat_list_friends` | 获取好友列表 |
| `napcat_list_unidirectional_friends` | 获取单向好友 |
| `napcat_get_user_profile` | 获取 QQ 资料 |
| `napcat_list_recent_contacts` | 获取最近会话 |
| `napcat_delete_friend` | 删除好友 |
| `napcat_list_pending_friend_requests` | 待处理好友申请 |
| `napcat_handle_friend_request` | 处理好友申请 |
| `napcat_list_doubt_friend_requests` | 可疑好友申请 |
| `napcat_handle_doubt_friend_request` | 处理可疑申请 |
| `napcat_set_friend_remark` | 设置好友备注 |
| `napcat_send_like` | 给资料点赞 |

### 消息与收藏（19 个）

| 工具 | 说明 |
|---|---|
| `group_vote` | 发起群投票：发布投票消息，群友点 👍 计票，达标后自动执行约定操作（如解禁），并拉起 planner 处理 |
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
| `napcat_fetch_message_emoji_like_detail` | 表情回应详情 |
| `napcat_ocr_image` | 图片 OCR 识别 |
| `napcat_add_favorite` | 收藏消息到全局收藏夹 |
| `napcat_list_favorites` | 查看收藏列表 |
| `napcat_send_favorites` | 把收藏合并转发到群里 |

### 资料与 AI 语音（5 个）

| 工具 | 说明 |
|---|---|
| `napcat_set_self_profile` | 修改自己的昵称、签名、性别 |
| `napcat_set_self_longnick` | 设置长个性签名 |
| `napcat_list_ai_characters` | 获取 AI 语音角色列表 |
| `napcat_send_group_ai_record` | 发送群 AI 语音 |
| `napcat_send_cosyvoice_record` | CosyVoice2 语音合成（支持情绪，推荐） |

### 系统与状态（10 个）

| 工具 | 说明 |
|---|---|
| `napcat_get_login_info` | 获取登录 QQ 信息 |
| `napcat_raw_action` | 调用原始 NapCat 动作 |
| `napcat_check_url_safely` | 检查链接安全性 |
| `napcat_url_safety_check` | 链接安全检查（始终安全） |
| `napcat_can_send_image` | 检查能否发图片 |
| `napcat_can_send_record` | 检查能否发语音 |
| `napcat_get_status` | 获取 NapCat 运行状态 |
| `napcat_get_version_info` | 获取版本信息 |
| `napcat_get_online_clients` | 获取在线客户端 |
| `napcat_get_user_online_status` | 获取用户在线状态 |

### 文件与执行（8 个）

| 工具 | 说明 |
|---|---|
| `napcat_download_file` | 从 URL 下载文件 |
| `napcat_download_qq_file` | 通过 NapCat 下载 QQ 文件 |
| `view_file` | 查看本地文件内容 |
| `write_file` | 写入文本文件（可写代码再执行） |
| `extract_file` | 解压压缩文件 |
| `run_command` | 直接运行 shell 命令（上限 30 秒，无需授权） |
| `execute_command` | 执行命令（需授权确认） |
| `fetch_webpage` | 获取网页 HTML |

### MC 服务器远程管理（9 个）

通过 SSH 管理本地 MC 机器（配置在 `config.toml` 的 `[minecraft_server]`），供 AI 部署/运维 Minecraft 服务端：

| 工具 | 说明 |
|---|---|
| `mc_server_status` | 查看 MC 服务运行状态（Java 进程、25565 端口） |
| `mc_server_start` | 启动 Minecraft 服务端 |
| `mc_server_stop` | 停止 Minecraft 服务端 |
| `mc_server_deploy` | 获取 MC 部署指引 |
| `mc_remote_view_file` | 查看本地 MC 工作目录文件 |
| `mc_remote_create_file` | 在 MC 工作目录创建文件 |
| `mc_remote_modify_file` | 修改 MC 工作目录文件 |
| `mc_remote_upload_file` | 上传服务器文件到 MC 机器 |
| `mc_remote_exec` | 在 MC 机器执行 Windows 命令 |

## 附属组件

### proxy_server.py（公网代理服务器）

部署在公网服务器上的 FastAPI 小服务，为无公网环境的 MaiBot 提供请求转发、投票/求情数据中转等能力。
`config.toml` 的 `[proxy]` 分区配置连接方式，`[plea]` 分区控制禁言求情功能。

### mc_agent（Minecraft 智能体插件）

`mc_agent/` 目录是一个独立的 MaiBot 插件：用 Mineflayer 无头客户端把 AI 接入 Minecraft 服务器，
支持多实例（群聊 ↔ 容器绑定）、事件决策（血量/死亡/聊天/定时状态）、Docker 隔离运行、DeepSeek LLM 决策。

- 运行前提：构建 MC 客户端镜像 `cd mc_agent/mc_client && docker build -t mc-client:latest .`
- 详细说明见 `mc_agent/_manifest.json` 与 `mc_agent/config.toml` 内注释
- 该插件同样依赖 `patches/` 中的外部 planner 补丁（`trigger_maisaka` 功能）

## 使用示例

以下是麦麦在群里的典型交互：

```
用户: @麦麦 看看这个群的公告
→ AI 调用 napcat_get_group_notices，获取公告列表并回复

用户: @麦麦 帮我把那个发广告的踢了
→ AI 调用 napcat_list_group_members 找到目标
→ AI 调用 napcat_kick_group_member 踢出

用户: @麦麦 发个群公告说今晚聚餐
→ AI 调用 napcat_send_group_notice 发布公告

用户: 我 QQ 3939129639 加你好友了
→ AI 调用 napcat_list_pending_friend_requests 查看并处理

用户: 访问一下这个网页 http://example.com
→ AI 调用 napcat_url_safety_check 检查安全
→ AI 调用 napcat_fetch_webpage 获取内容

用户: @麦麦 发起个投票，决定今晚要不要开 MC 服务器，3 票通过
→ AI 调用 group_vote 发布投票消息，群友点 👍 计票
→ 达标后自动宣布通过，并调用 maisaka.external.task 拉起 planner 执行约定操作
```

## 风险工具的处理

禁言、踢人、退群等高风险操作，AI 会结合上下文自行判断。如果配置的是 DeepSeek 或 Qwen3-32b 级别模型，判断质量较高。

## FAQ

**Q: AI 总是搜不到工具怎么办？**
A: 安装 tool_search 补丁即可，支持用自然语言搜工具名。

**Q: AI 回复时编造数字？**
A: 安装 maisaka_generator_base 补丁，replyer 能看到工具返回的真实数据。

**Q: AI 连着回复十几条？**
A: 安装 reasoning_engine 补丁，reply 后强制结束循环。

**Q: 群投票达标后没有反应？**
A: 确认已用 `patches/patch_tool.py` 安装主程序补丁（外部 planner 功能依赖 `maisaka.external.task`），并重启主程序。

**Q: 需要什么 NapCat 版本？**
A: 所有接口都是 NapCat 标准动作，版本无关。

**Q: 命令执行工具怎么授权？**
A: 在 WebUI 插件面板的「安全」分区填写 `command_confirm_qq`，填入你的 QQ 号。之后只有你的 QQ 发送"执行"才能触发命令。留空则不限制任何用户。

## 协议

MIT

## 作者

DZY
