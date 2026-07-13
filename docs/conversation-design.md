# 会话与消息持久化设计

## 1. 目标

将当前只存在于 Vue 内存中的聊天记录保存到 MySQL，使用户刷新页面后仍能查看历史会话并继续提问。

本阶段只保存业务历史，不保存 API Key、完整 Prompt 或模型内部推理过程。

## 2. 数据关系

```text
Conversation 1 ── N Message 1 ── N MessageSource
```

- `Conversation`：一组连续问答，例如“高血压资料查询”。
- `Message`：用户问题或助手回答，通过 `sequence` 保证显示顺序。
- `MessageSource`：只属于助手回答，保存当时使用的文件、页码和引用片段。

删除会话时，数据库通过级联关系删除其消息和引用来源。

## 3. 核心字段

### conversations

| 字段 | 说明 |
| --- | --- |
| id | UUID，会话唯一标识 |
| title | 会话标题，第一版可由首个问题截取生成 |
| created_at | 创建时间 |
| updated_at | 最近活动时间，列表按此倒序 |

### messages

| 字段 | 说明 |
| --- | --- |
| id | UUID，消息唯一标识 |
| conversation_id | 所属会话 |
| sequence | 会话内严格递增的顺序号 |
| role | `user` 或 `assistant` |
| content | 用户问题或最终展示的回答 |
| status | `pending`、`completed`、`failed`、`stopped` |
| request_id | 助手回答对应的请求标识，可为空 |
| created_at | 创建时间 |

### message_sources

| 字段 | 说明 |
| --- | --- |
| id | 自增主键 |
| message_id | 所属助手消息 |
| position | 引用在回答中的显示顺序 |
| file_name | 来源文件名 |
| page | PDF 页码，TXT 可为空 |
| content | 当时引用的原文片段 |

## 4. 流式消息保存规则

1. 收到问题时，先保存用户消息。
2. 创建状态为 `pending` 的助手消息。
3. SSE token 只发送给浏览器，不对每个 token 单独写数据库。
4. 正常收到模型结束后，一次性保存完整回答和引用，状态改为 `completed`。
5. 用户主动停止时，保留已生成文字并标记 `stopped`。
6. 模型失败时标记 `failed`，不保存虚构来源。

这样可以避免每个 token 都执行一次 SQL，同时保留中断和失败事实。

## 5. 计划接口

```text
POST   /api/v1/conversations
GET    /api/v1/conversations
GET    /api/v1/conversations/{conversation_id}
PATCH  /api/v1/conversations/{conversation_id}
DELETE /api/v1/conversations/{conversation_id}

POST   /api/v1/conversations/{conversation_id}/chat
POST   /api/v1/conversations/{conversation_id}/chat/stream
```

现有 `/api/v1/chat` 和 `/api/v1/chat/stream` 暂时保留为无会话兼容接口。

当前实现进度：会话 CRUD、带会话普通/流式问答、最近 3 轮上下文、Vue 历史会话列表和删除确认均已完成。页面可新建、切换、恢复和删除会话，通过带会话 SSE 接口继续提问。删除当前会话后自动切换到剩余最近会话，无剩余会话时回到欢迎状态。

Vue 组件测试直接挂载 `ChatView.vue` 并模拟会话 API，自动检查每个 SSE token 是否立即进入页面、切换历史后是否显示正确消息，以及删除取消/确认和自动切换是否符合预期。

## 6. 第一版边界

- 当前还没有用户登录，因此会话暂不区分用户；加入认证后再增加 `user_id`。
- 第一版不保存模型内部推理过程。
- 第一版不把完整医学文档复制进 MySQL，只保存回答实际引用的片段。
- 数据库密码只放在后端 `DATABASE_URL` 环境变量中。
