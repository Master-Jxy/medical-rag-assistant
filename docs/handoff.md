# 当前开发交接

> 最后更新：2026-07-17
> 这是新账号、新对话或新开发者的第一状态入口。本文只记录当前真实状态和一个下一任务，不保留按时间累积的开发流水账。

## 1. 开始前必读

按顺序阅读：

1. `AGENTS.md`：开发规则、模块边界和验证要求。
2. 本文：当前真实状态和唯一下一任务。
3. `docs/development-roadmap.md`：当前阶段的任务拆分与验收。
4. `docs/technical-design.md`：现状、目标架构、数据和接口设计。
5. 与下一任务直接相关的代码和测试。

不要依赖旧聊天记录推断需求。代码和测试优先于文档；发现冲突时，在本次任务中修正文档。

## 2. 项目当前结论

**核心 MVP 已完成，全部企业化增强尚未完成。**

当前项目是可运行的 Vue 3 + FastAPI + MySQL + Chroma 医疗 RAG 应用，具备：

- PDF/TXT 上传、解析、切分、SHA-256 去重、向量化、列表和一致删除。
- 通义千问问答、DashScope Embedding、Chroma 检索、引用来源和知识不足拒答。
- SSE 逐块输出、主动停止、完成/失败/中止状态处理。
- MySQL 会话、消息、引用来源持久化。
- Alembic 会话三表基线、`users` 表、邮箱唯一约束和 Argon2 密码哈希基础。
- 邮箱注册、登录、30 分钟短期 Bearer JWT 和当前用户接口。
- Vue 注册登录、Token 保存与刷新恢复、退出、路由守卫、统一 401 处理和原目标页返回。
- 会话非空用户归属，以及列表、详情、改名、删除、普通问答和 SSE 问答的跨账号隔离。
- MySQL 文档登记、公共文档读取、新文档上传者归属、上传者删除权限和系统文档保护。
- 数据库可信的 `user/admin` 角色、统一 `require_admin`、受控角色维护命令和 `/auth/me` 角色返回。
- 系统文档新增、删除、整份替换，共享跨 MySQL、文件和 Chroma 的生命周期及失败补偿。
- 独立 `/admin/knowledge` 管理页面、管理员路由守卫和独立前端 API 模块。
- 可选 Redis 配置、惰性连接适配器、有限超时、关闭释放以及 `ok/disabled/degraded` 健康状态。
- 注册和登录按规范化 IP 的独立窗口限流、统一 429/`Retry-After`、可信代理边界和 Redis 故障时的有界本机兜底。
- 四个问答入口共享按用户的分钟级额度，超限在检索、模型和 SSE 响应开始前返回统一 JSON 429。
- 普通上传使用按用户的小时级额度与并发占位；管理员新增和替换系统文档跳过小时次数限制，但仍保留带所有权/TTL 的并发占位，一次只处理一个文件。两类拒绝都发生在文档生命周期和 Embedding 之前。
- 会话非流式和 SSE 问答共享“当前用户 + 会话”生成锁，使用随机所有权令牌、有限 TTL 和原子比较释放；Redis 状态不明确时在模型调用前明确拒绝。
- 会话问答使用受约束的 `Idempotency-Key`；重复普通请求从 MySQL 恢复原结果，重复 SSE 请求稳定回放，不重复保存消息、检索或调用模型。
- 会话 SSE 使用独立停止接口和可取消的 DashScope 异步 HTTP 流；后端取消本地读取并关闭流连接，将部分回答保存为 `stopped`、清理幂等记录并释放生成锁，前端收到停止事件和流结束后才恢复发送。
- Redis 四类保护能力共享可观测状态：限流与上传并发明确为本机兜底，生成锁与幂等明确为 fail-closed；健康接口返回各功能模式与成功/失败/恢复计数，持续故障日志按状态迁移去重。
- 最近 3 轮有效上下文、刷新恢复、会话增删改查。
- Vue 概览、知识库和问答页面。
- 后端 pytest、前端组件、SSE 字节分片和 Vite 构建验证。

2026-07-17 已在任务 6.4b 完成后的真实代码和页面验收基础上同步状态，`RAG v1.1` 已冻结。项目继续采用**模块化单体**，不拆微服务；后续开发固定沿着“Router -> Application Service -> Port -> Adapter”的方向增量演进。RAG、Agent、认证、知识库和会话拥有独立模块边界，Agent 不替换普通 RAG，也不能直接访问 Repository、Chroma、Redis 客户端或系统命令。

当前尚未实现：

- 版本化 RAG 评估集、混合检索和 Reranker。
- 结构化监控页面。
- 独立 Agent 模块。
- HTTPS/域名、自动备份和云端上传/问答/重启恢复完整验收。

部署基线已于 2026-07-17 完成：仓库具备 MySQL、Redis、FastAPI、Vue/Nginx 的 Compose 编排、持久卷、健康检查和资源上限，并已在 Ubuntu 22.04、2 核 2G 阿里云 ECS 上通过公网首页、健康接口、注册、登录、当前用户、创建会话和文档列表验收。公网 HTTP 环境不提供原生 `crypto.randomUUID()`，前端统一 UUID 工具会优先使用原生实现，并在 HTTP/旧浏览器中安全降级，保证聊天临时消息和幂等键可以生成。当前仅开放 HTTP，真实账号不得复用其他网站密码；部署和更新命令以 `docs/deployment.md` 为准。

目标演进顺序已经固定为：

```text
Redis 接口保护
-> RAG 评估与检索优化
-> 可观测性
-> 受控资料整理 Agent
-> HTTPS、备份恢复与云端完整验收
```

对标公开成熟项目时只学习模块边界、工具注册、状态机、评估、审计和故障恢复，不在当前阶段复制多 Agent、可视化工作流、插件市场、消息队列或 Kubernetes。

## 3. 已确认的下一阶段产品规则

- 使用邮箱和密码注册登录。
- 每个账号只看到自己的聊天历史。
- 现有会话是测试数据：迁移前备份，迁移时清空。
- 所有知识库文档保持公共，登录用户都可检索。
- 新上传文档同样公共，但只有上传者可以删除。
- 系统预置文档不能由普通用户删除。
- 第一版使用短期 Bearer JWT。
- 基础登录版本不做邮箱验证码、找回密码和 Refresh Token。
- 管理员通过独立接口管理系统文档；普通用户现有公共上传规则保持不变。

## 4. 当前代码入口

后端：

- 正式 FastAPI 入口：`backend/app/main.py`
- 兼容入口：`backend/main.py`
- 路由：`backend/app/api/`
- 业务服务：`backend/app/services/`
- 数据模型：`backend/app/models/conversation.py`
- 认证基础：`backend/app/modules/auth/`
- 文档模型和登记仓储：`backend/app/modules/knowledge/`
- 共享文档生命周期：`backend/app/modules/knowledge/lifecycle.py`
- 管理员文档服务：`backend/app/services/admin_document_service.py`
- 受控角色维护命令：`backend/scripts/set_user_role.py`
- Alembic：`backend/alembic.ini`、`backend/alembic/`
- Chroma 封装：`backend/app/infrastructure/vector_store.py`
- Redis 封装：`backend/app/infrastructure/redis.py`
- 共享限流端口与故障切换：`backend/app/ports/rate_limit.py`、`backend/app/services/rate_limit_service.py`
- 聊天限流策略：`backend/app/services/chat_rate_limit_service.py`
- 上传保护：`backend/app/services/upload_protection_service.py`
- 并发占位端口与适配器：`backend/app/ports/concurrency_limit.py`、`backend/app/infrastructure/local_concurrency_limit.py`
- 生成锁端口与服务：`backend/app/ports/distributed_lock.py`、`backend/app/services/generation_lock_service.py`
- 幂等端口与服务：`backend/app/ports/idempotency.py`、`backend/app/services/idempotency_service.py`
- 可取消模型流适配器：`backend/app/infrastructure/async_chat_model.py`
- 健康状态服务：`backend/app/services/health_service.py`
- 测试：`backend/tests/`

前端：

- 路由：`frontend/src/router/index.js`
- 页面：`frontend/src/views/`
- API：`frontend/src/api/`
- 认证状态和 Token：`frontend/src/auth/`
- 测试：`frontend/tests/`

运行数据：

- 文档主登记：MySQL `documents` 表
- 旧登记快照：`backend/data/documents.json`（迁移完成后不再参与运行时读写）
- 上传文件：`backend/data/`
- 向量库：由 `.env` 的 `CHROMA_PERSIST_DIR` 决定
- MySQL：由 `.env` 的 `DATABASE_URL` 决定
- Redis：本机已通过 `REDIS_URL=redis://127.0.0.1:6379/0` 接入 D 盘 Memurai Developer，健康状态为 `ok`；登录后由启动项自动拉起
- 上述运行数据不提交 Git

## 5. 当前本地数据快照

截至 2026-07-17：

- 原 36 份短文档已通过共享文档生命周期全部删除；替换前数据库与存储备份位于 `backend/backups/before_knowledge_refresh_20260717_012243/`。
- MySQL 公共系统文档数：27；全部来自桌面“医疗文档”目录，上传者均为空，普通用户不可删除。
- Chroma 文本片段数：103；MySQL 登记片段 ID、Chroma 数量和磁盘文件已逐项核对一致。
- 27 份源文件与入库记录的 SHA-256 全部一致，无缺失文件、未知登记或临时删除文件。
- 替换前数据库备份 `medical_rag.sql` 的 SHA-256：`BBA0638CE118AFA4A66E194B674915FC163A20F4F17E372E6D830598ACB1B057`。
- 替换前文件与 Chroma 备份 `knowledge_storage.zip` 的 SHA-256：`48E0B88795B50EAA9D50BE321715F4CC1303F4FD6C4F90DDE90F39A55BF779DA`。
- `backend/scripts/import_documents.py` 通过系统文档生命周期批量导入，要求 `--confirm` 且重复内容幂等跳过；`backend/scripts/migrate_document_registry.py` 负责旧 JSON 登记的一次性幂等迁移。
- MySQL 迁移版本：`0005_user_role`；现有 2 个账号均保持普通用户角色。
- 当前用户、会话、消息、引用数量：3、2、14、20；这是现有正常数据，不得作为临时数据清理。本次停止验收创建的 `stop-check-*` 临时账号和其会话已确认删除。
- 迁移前备份：`backend/backups/before_auth_migration_20260715_010920.sql`（被 Git 忽略）。
- 会话归属迁移备份：`backend/backups/before_conversation_ownership_20260715_014819.sql`（被 Git 忽略）。
- 文档迁移前数据库备份：`backend/backups/before_document_registry_20260715_022247.sql`（被 Git 忽略）。
- 文档迁移前文件、旧 JSON 和 Chroma 备份：`backend/backups/before_document_storage_20260715_022247.zip`（被 Git 忽略，SHA-256：`B7CCFB1CB5F0E48A0A62097AF09848DDA2417D678157CD24348423191421C32E`）。
- 管理员迁移前数据库备份：`backend/backups/before_admin_20260715_130405.sql`（被 Git 忽略，SHA-256：`88956B936B9C67AF81AB20965300A1E6B6BB3A8D57BE5F4A5AE9C04636C09512`）。
- 管理员迁移前文件和 Chroma 备份：`backend/backups/before_admin_storage_20260715_130405.zip`（被 Git 忽略，SHA-256：`CD723C81E9EF50B85EDFEF5AE3B106D8EE20EEF702876093284EF8CFB1D0B10C`）。

这是本地快照，不应硬编码到页面或业务逻辑。迁移脚本可重复运行，已导入登记会被跳过，也不会重新调用 Embedding。

## 6. 当前工作区注意事项

当前仓库仍包含本轮连续开发产生的大量未提交修改和未跟踪文件，覆盖认证、会话、知识库、管理员、Redis、测试与文档；它们共同组成当前可运行版本，并不代表应删除的临时内容。

新任务不得执行 `git reset --hard`、`git checkout --` 或批量清理未跟踪文件。开始编码前必须查看 `git status` 和与当前任务相关的 diff，只在现有实现上继续；遇到其他窗口刚产生的变化时，以代码和测试为准并同步文档。

## 7. 最近一次完整验证

2026-07-17 任务 6.4b 完成后的最近完整验证：

- 后端：114 项通过；覆盖模型流取消、`stopped` 持久化、幂等清理、停止后锁释放，以及管理员跳过上传频率但仍保留并发限制；原认证、会话、RAG、Redis、文档补偿和管理员测试无回归。
- Vue：8 个测试文件、29 项测试通过，覆盖原登录闭环、文档权限、管理员交互、稳定错误提示、SSE 读取器取消、等待后端停止确认后恢复发送，以及公网 HTTP 环境缺少 `crypto.randomUUID()` 时的兼容 UUID 生成。
- SSE UTF-8 字节分片测试：通过。
- Vite 正式构建：通过。
- 真实 HTTP 已完成一次付费模型生成：回答 338 字、4 个引用；同一幂等请求重复提交返回相同请求和消息 ID，没有第二次调用模型。短期 Redis 占位验证两类 409 后已清理；临时账号、会话和 Redis 键也已删除。
- 真实页面使用长回答复测：生成中点击停止后约 2.5 秒恢复输入，同一会话立即再次提问并正常完成，没有 409 生成冲突；停止后的部分回答保存为 `stopped`。验收临时账号和会话已删除。
- 会话 SSE 已改用可取消的 DashScope 异步 HTTP 流；停止会取消本地读取任务并关闭底层响应流，不再等待模型自然返回下一块。本轮没有数据库迁移或安装软件，`RAG v1.1` 已冻结。

已知非阻断警告：

- Starlette TestClient 的 httpx 兼容性弃用提示。
- `langchain-community` 的未来拆包提示。

警告后续单独处理，不要在文档权限任务中顺手大规模升级依赖。

## 8. 本地启动

### 8.1 MySQL

本机 MySQL 8.4.9 安装在 `D:\MySQL`，当前未注册为 Windows 服务。重启电脑后，如数据库未启动，可使用：

```powershell
Start-Process "D:\MySQL\bin\mysqld.exe" -ArgumentList "--defaults-file=D:\MySQL\my.ini" -WindowStyle Hidden
```

不要把数据库密码写入文档、命令历史或 Git。

### 8.2 后端

编辑本地 `backend/.env` 时还必须配置长度不少于 32 个字符的随机 `JWT_SECRET_KEY`；真实值不得提交 Git。

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m alembic -c alembic.ini upgrade head
python -m uvicorn app.main:app --reload
```

- API：`http://127.0.0.1:8000`
- OpenAPI：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/api/v1/health`

认证功能交付前不能只看测试或健康检查，还必须在不输出密钥值的前提下完成：

1. 确认 `JWT_SECRET_KEY` 存在且长度不少于32个字符。
2. 确认真正监听8000端口的是读取当前配置的后端进程；使用 `--reload` 时注意旧子进程可能继续占用端口。
3. 对真实运行中的后端执行一次登录并获得 Bearer Token。
4. 使用该 Token 请求 `/api/v1/auth/me` 并确认返回对应用户。
5. 页面刷新、退出和401失效流程也通过后，才能宣称登录闭环可用。

### 8.3 前端

```powershell
cd frontend
D:\Nodejs\npm.cmd run dev
```

- 页面：`http://127.0.0.1:5173`

## 9. 验证命令

从项目根目录执行：

```powershell
backend\.venv\Scripts\python.exe -m pytest -q backend\tests
D:\Nodejs\npm.cmd --prefix frontend test
D:\Nodejs\npm.cmd --prefix frontend run test:stream
D:\Nodejs\npm.cmd --prefix frontend run build
```

涉及页面行为时，还要真实打开浏览器检查；涉及删除或迁移时，要检查目标数据和无关数据。

## 10. 唯一下一任务

开始路线图中的 **任务 7.1：RAG 评估集与当前基线**。

```text
建立版本化的 30-50 题评估集，包含期望来源、关键事实和知识不足拒答样例；先运行当前系统得到来源命中率、拒答准确率、延迟和费用基线，不修改检索算法。
```

开始前应先检查：

- 评估数据与真实用户会话分开保存，不把测试问题写入 MySQL 会话历史。
- 先定义问题类别、期望文档和评分规则，再运行基线，禁止根据单次回答临时修改标准。
- 默认使用可重复的检索评估；真实模型回答评估必须有明确上限，避免无意义额度消耗。
- 不修改检索算法、RAG Prompt、数据库结构、Agent 或 Docker。
- 用户未提交的工作区改动。

任务完成标准以 `docs/development-roadmap.md` 的任务 7.1 为准。完成后更新本文的状态、验证结果和唯一下一任务。
