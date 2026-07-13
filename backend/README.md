# Backend

医疗知识库智能问答系统的 FastAPI 后端。

## 启动方式

在 `backend` 目录打开 PowerShell，执行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

启动后可访问：

- 接口文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/v1/health>
- 普通问答：在接口文档中测试 `POST /api/v1/chat`
- 流式问答：`POST /api/v1/chat/stream`，响应类型为 `text/event-stream`
- 上传文档：在接口文档中测试 `POST /api/v1/documents`
- 文档列表：`GET /api/v1/documents`
- 删除文档：`DELETE /api/v1/documents/{document_id}`

健康检查的预期响应：

```json
{"status":"ok"}
```

问答请求示例：

```json
{
  "question": "小户型选择扫地机器人时应该关注什么？",
  "top_k": 3
}
```

当前 Chroma 临时复用了原课程的扫地机器人资料，只用于验证 RAG 链路。后续文档管理阶段会换成来源清晰的医学资料。

## 上传文档

在 `/docs` 展开 `POST /api/v1/documents`，选择一个 PDF 或 UTF-8 TXT 文件并执行。

当前规则：

- 只支持 `.pdf` 和 `.txt`。
- 单个文件最大 10 MB。
- 使用 SHA-256 判断内容是否重复；即使文件名不同，相同内容也不会重复向量化。
- 上传成功返回 HTTP 201、文档 ID 和片段数量。
- 上传和问答会调用阿里云模型服务，请避免重复执行造成额外费用。

删除成功后，后端会同步删除上传原文件、文档登记记录和对应的全部 Chroma 向量片段。获取列表和删除文档不会调用模型，不产生模型费用。

## 会话数据库配置

会话历史计划使用 MySQL + SQLAlchemy。请在本地 `.env` 中配置：

```env
DATABASE_URL=mysql+pymysql://用户名:密码@127.0.0.1:3306/medical_rag?charset=utf8mb4
```

数据库密码不得提交到 Git。当前本机 MySQL 已接通，并提供：

- `POST /api/v1/conversations`
- `GET /api/v1/conversations`
- `GET /api/v1/conversations/{conversation_id}`
- `PATCH /api/v1/conversations/{conversation_id}`
- `DELETE /api/v1/conversations/{conversation_id}`
- `POST /api/v1/conversations/{conversation_id}/chat`
- `POST /api/v1/conversations/{conversation_id}/chat/stream`

带会话普通问答会先保存用户消息和 pending 助手消息，再调用 RAG；成功后保存完整回答、引用和请求 ID，失败则把助手状态更新为 `failed`。

带会话流式问答同样先创建 pending 消息：正常结束保存为 `completed`，流中错误保存为 `failed`，客户端断开保存为 `stopped`；token 不逐条写数据库。

带会话的普通和流式问答都会在生成当前回答前，从 MySQL 读取最近 3 轮有效历史并交给模型。`pending`、`failed` 消息不会进入上下文，历史总长度由 `MAX_HISTORY_CHARS` 限制。无会话兼容接口 `/api/v1/chat` 和 `/api/v1/chat/stream` 仍保持单轮问答。

Vue 问答页已经使用上述会话接口：进入页面时读取会话列表，切换会话时读取消息详情，发送问题时调用带会话 SSE 接口，因此刷新浏览器后仍可恢复历史并继续追问。
历史列表也支持二次确认后删除会话；后端通过级联关系同步删除该会话的消息和引用来源。

前端组件测试使用 Vitest、Vue Test Utils 和 happy-dom，运行方式：

```powershell
cd ..\frontend
& 'D:\Nodejs\npm.cmd' test
```

> 本项目仅供学习和信息检索，不构成医疗建议。
