# 当前开发交接

> 最后更新：2026-07-25
> 本文件只保留当前事实、验证边界和一个下一任务。

## 1. 新任务读取范围

完整阅读：

1. `AGENTS.md`
2. 本文件

下一任务定向阅读：

- `docs/development-roadmap.md` 的阶段9任务9.1
- `docs/technical-design.md` 第12节
- 只有发布、回滚或复核线上证据时才读取 `docs/release-audit-rag-v1.3.md` 和 `docs/deployment.md`

## 2. 当前状态

项目是 Vue 3 + FastAPI + MySQL + Chroma + Redis + DashScope 的模块化单体。

- 阶段7已经完成：`RAG v1.2.1`已部署，最终受控线上验收通过。
- 阶段8的任务8.1～8.5已经完成，并作为`RAG v1.3`提交、推送和部署。
- 服务器运行`RAG v1.3`代码提交`1ca9bc059b499b69fd0b9d82d2f2df36e4cfe228`，四个容器健康。
- 本轮阶段8部署没有调用真实Embedding、Reranker或Qwen，没有产生模型费用；临时验收账号已删除，业务数据恢复原基线。

## 3. 阶段7最终证据

最终受控验收实际使用3次Embedding业务调用、2次Qwen SSE、0次Reranker和0次自动重试，费用估算约0.01～0.03元：

- 临时上传后MySQL文档、Chroma片段和文件由27/103/27同步变为28/104/28。
- 短问答收到19个token事件、4个来源、正确医学事实、临时来源和`done`。
- 长问答在首个token后约73毫秒停止；状态为`completed, stopped`，生成锁释放，停止接口为`idle`，同会话幂等回放成功。
- 临时文档、会话和账号已删除；最终恢复27份文档、103个片段、27个文件、4个账号、5个会话和40条消息，五类临时残留均为0，四个容器健康。

详细发布与失败尝试历史只查`docs/release-audit-rag-v1.2.1.md`。

## 4. 阶段8实际能力

- 8.1：`TelemetryPort`、固定安全事件、JSON结构化日志和贯穿请求的`request_id`。
- 8.2：使用单调时钟记录HTTP、查询构造、向量检索、可选重排、模型生成阶段耗时，并预留工具阶段。
- 8.3：进程内聚合请求、成功/失败、耗时、限流、Redis降级、主动停止、三类基础设施失败及Token/费用状态；缺少可靠计量时明确返回未知。
- 8.4：管理员只读`GET /api/v1/admin/telemetry/stats`及独立前端统计页；普通用户稳定返回403。
- 8.5：覆盖Redis不可用、Chroma失败、模型超时、Telemetry自身失败、SSE停止、未知Token、越权和关闭Telemetry；日志按5 MiB轮转并保留5份备份。
- Docker默认将Telemetry日志写入已有`app_data`卷的`/app/data/logs/telemetry.jsonl`，可以通过环境变量关闭或调整保留上限。

Telemetry只观察业务，不记录完整问题、回答、Prompt、密码、JWT、API Key、邮箱或医学正文；关闭或写入失败都不能改变原业务结果。

## 5. 最新验证

2026-07-25发布前回归：

- 后端完整测试：250项通过。
- 前端完整测试：9个文件、30项通过。
- SSE UTF-8分片测试：通过。
- Vite正式构建：通过。
- `pip check`：无依赖冲突。
- Alembic：`0005_user_role (head)`，单头。
- Compose YAML及四项Telemetry容器配置：通过。
- 架构边界、日志脱敏、轮转/关闭和故障注入：通过。
- 新增内容敏感信息扫描和`git diff --check`：通过。

2026-07-25服务器部署与验收：

- 部署前服务器提交为`70f5c5a`，工作树干净，27份文档、103个Chroma片段、27个文件、4个账号、5个会话和40条消息。
- MySQL、`app_data`、`chroma_data`、Redis、`deploy/.env`和旧前端均已备份并通过SHA-256校验；后端和Web旧镜像保留回滚标签。
- 服务器快进到`1ca9bc0`，只重建`backend`和`web`，MySQL、Redis及命名卷没有删除或重建。
- 首次上传的前端包缺少生产`VITE_API_BASE_URL=/api/v1`，真实浏览器显示后端连接失败；验收立即捕获后重新按部署手册构建，只重建Web，最终首页显示“运行正常”。
- 未登录统计接口401、普通用户403、管理员200；登录后的`/admin/telemetry`页面真实浏览器验收通过，聚合卡片、未知Token/费用、阶段耗时和错误类型正常展示。
- Telemetry写入`/app/data/logs/telemetry.jsonl`，当前只有1个受控日志文件；临时邮箱和密码均未进入日志。
- 临时管理员账号已删除，最终恢复27/103/27、4账号/5会话/40消息，四容器健康、Redis `PONG`、服务器工作树干净。

## 6. 工作区与禁止事项

- 当前分支为`main`；`RAG v1.3`代码提交为`1ca9bc0`。
- 阶段8代码、阶段7最终验收校验器、测试和文档已按`docs/release-audit-rag-v1.3.md`精确提交并推送。
- `backend/tests/test_auth_api.py`在`git status`中可能因Windows换行显示修改，但内容与HEAD一致，不属于发布范围。
- 不得清理、覆盖或回退现有修改；禁止`git reset --hard`和批量清理。
- 未经用户明确确认，不得部署或修改线上配置。

## 7. 唯一下一任务

**任务9.1：建立`modules/agent`骨架、Tool Protocol、Tool Registry和默认关闭的功能开关，只用Mock验证，不调用真实模型。**
