# 当前开发交接

> 最后更新：2026-08-06
> 本文件只保留当前事实、工作区边界和一个下一任务。

## 1. 当前真实状态

Stage 24.1 解析契约已经完成本地开发与无模型验证，未部署、未调用真实模型或 Embedding。
本次只在 `knowledge` 模块内新增结构化解析契约与 registry，并为现有
`LocalDocumentParser` 增加兼容适配；PDF/TXT 上传、预览截断、质量警告、审核发布、
切片和 Chroma 外部行为保持不变。未新增 DOCX、Markdown、HTML、网页、OCR 或视觉实现，
未安装重型依赖，未改 API 响应、数据库或生产配置。

24.1 借鉴边界：Docling 的统一转换出口思想、Unstructured 的统一 Element 模型、Haystack
的 Converter/Splitter 组件分层；没有复制第三方源码，也没有把第三方对象传入业务服务。

Stage 24.0 稳定性收尾已经完成本地无模型复核，未修改业务代码，未实现 24.1 及之后的
解析能力。复核范围只覆盖 RAG/Agent 跨页面流式继续、后台未读与重新打开已读、陈旧
pending 恢复、明确停止、退出/401 清理、构建输出和测试控制台错误。现有覆盖充分，
未发现需要为了“有产出”而修代码的缺陷。

Stage 23 运行中断恢复已经完成并发布，生产代码提交为 684e4c1。发布前完整备份、
指定提交同步、backend 单服务重建和无费用线上验收均通过，未调用真实模型。

RAG/Agent 跨业务页面流式恢复缺陷已修复并发布，生产业务提交为 `c900235`：

- RAG 和 Agent 的 stream registry、Agent timeline 提升为模块级共享状态；普通路由
  卸载不再 abort，返回页面继续显示原草稿、计划、工具事件和后续 token。
- 明确停止、退出登录和认证失效仍会中止并清空流状态，不跨账号保留消息。
- 医学疾病、症状、用药、检查、治疗和就医知识问题确定性调用
  `search_knowledge`；通用闲聊仍可直接回答。
- Agent 工具回答和 direct reply 最终正文都走真实流式 finalizer；不再把规划阶段完整
  回答作为一个整块 token 事件发给前端。

Stage 22 的 22.1～22.8 已完成并发布，功能提交为 `5c02056`，随后发布记录提交为
`92dd751`。生产 Alembic head 为 `0026_stage22_runtime_contract`。生产使用 HTTPS
入口，MySQL、Redis、应用数据和 Chroma 数据卷均保留，Stage 22 没有启用新的真实模型调用。

本阶段已实现：

- 管理员统一替换和永久删除系统资料、用户审核后发布的资料；普通用户不能永久删除已发布公共资料。替换保留上传者、标签、分类、科室和治理元数据，并同步关联 submission。
- 跨 MySQL、文件和 Chroma 的删除/替换继续使用行锁、审计和可补偿流程。
- 新增迁移 `0026_stage22_runtime_contract`：RAG 会话和 Agent thread 增加 `last_read_sequence`，Agent thread 增加 `assistant_mode`。
- 会话列表返回运行状态、active run、未读状态和最后消息状态；read marker 只能前移。
- RAG 与 Agent 共用每用户并发槽位，默认最多同时运行 2 个不同会话；同一会话仍保持单生成锁。
- RAG 与 Agent 前端均使用按会话 stream registry。会话 A 生成时可切换或新建会话 B，并在 B 继续提问；A 后台完成后显示未读点，重新打开后清除。
- 停止只影响当前选中会话；运行中的会话不能删除或归档。
- Agent 增加 `general/patient/clinician/knowledge` 四种后端强制模式。
- Agent 增加受控 supervisor/specialist 路由：最多 2 个 specialist、1 次 handoff、3 次工具调用、4 次模型调用。它不是自由群聊式或并行多 Agent。
- 显式引用可解析已有来源；工具结果摘要限制为 1200 字符；确定性工具结果跳过不必要的 inspection 模型调用；重复澄清键阻止相同循环。
- 公开计划和事件只来自后端白名单模板，不展示或持久化模型隐藏推理。

完整设计和对标证据：

- `docs/stage22-concurrent-agent-and-governance-design.md`
- `docs/stage22-benchmark-and-design-research.md`

## 2. 本地验证结果

```text
backend\.venv\Scripts\python.exe -m pytest -q backend\tests\test_document_parser_contract.py backend\tests\test_parser_experiments.py backend\tests\test_knowledge_submissions_api.py backend\tests\test_admin_reviews_api.py
12 passed, 2 warnings

backend\.venv\Scripts\python.exe -m pytest -q backend/tests
481 passed, 113 warnings

backend\.venv\Scripts\python.exe -m pytest -q backend\tests\test_conversation_recovery.py backend\tests\test_conversations_api.py backend\tests\test_conversation_stream_chat.py backend\tests\test_agent_conversation_api.py
23 passed, 2 warnings

D:\Nodejs\npm.cmd --prefix frontend test
18 files / 72 tests passed

D:\Nodejs\npm.cmd --prefix frontend test -- ChatView.test.js AgentView.test.js ConversationStreamRegistry.test.js ApiAuth.test.js
4 files / 33 tests passed

D:\Nodejs\npm.cmd --prefix frontend run test:stream
SSE parser test passed

D:\Nodejs\npm.cmd --prefix frontend run build
Vite production build passed
assets: index-COHvwHZI.css / index-BliWlH2I.js

backend\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini heads
0026_stage22_runtime_contract (head)

git diff --check
passed; only expected Windows line-ending notices

Protected auth hash
9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0
```

Stage 24.0 未做生产数据写入或线上生成验证。当前仓库没有安全、明确的真实公网 IP/SSH
目标可用于本任务的只读生产连接，因此生产健康、容器、迁移、静态资源和错误计数检查
本轮跳过；禁止猜测连接信息。未调用 Qwen、Embedding、Reranker、OCR、视觉或 SMTP。

浏览器无模型/无持久化 stub 验收通过：桌面和 390px 移动端均完成 RAG/Agent 并发、独立
停止、后台未读、重新打开清除未读、运行中删除禁用、四种 Agent 模式、固定输入器和溢出
检查；本次又验证了 RAG/Agent 跨业务页面返回、活动草稿复用、Agent知识库计划、工具、
来源和最终回答，控制台无错误。全部使用浏览器接口桩，没有调用模型或写入真实数据库。

## 3. 生产发布证据

- 本次修复完整备份目录：
  `/home/deploy/medical-rag-backups/backup-20260803T154055Z`；MySQL、app_data、
  chroma_data、redis_data、deploy.env、compose.yaml 和 manifest 的 SHA-256 全部通过。
- 服务器从 `f6ce7e2` 快进到 `c900235`。直连 GitHub 遇到已知 HTTP/2 接收中断后，
  改用本地验证过的完整 Git bundle 做 `fetch + merge --ff-only`，没有在线编辑源码。
- 本地 `frontend/dist` 原子替换服务器构建输入，只重建 backend/web；MySQL、Redis 和
  四个命名卷未重建，没有数据库迁移。四容器最终均为 healthy，生产工作区干净。
- HTTP 返回 308 到固定 HTTPS；HTTPS 健康接口返回 200；未登录会话接口返回 401；
  Alembic 仍为 `0026_stage22_runtime_contract`。
- 线上 JS/CSS 与本地 SHA-256 一致：
  `index-BliWlH2I.js` 为 `333cbd4b...dba07`，
  `index-COHvwHZI.css` 为 `eaf5ccd3...8d70`。
- 发布前后核心数量完全不变：users 14、conversations 9、messages 172、documents 27、
  agent_threads 7、agent_messages 76；最近 backend/web 日志错误匹配数为 0。
- 本次只做无费用健康、权限、迁移、静态资源、数据一致性和日志验收，没有调用 Qwen、
  Embedding、Reranker 或 SMTP，没有创建生产测试消息。
- 生产备份目录：`/home/deploy/medical-rag-backups/backup-20260803T012857Z`。
- 备份中的 MySQL、app_data、chroma_data、redis_data、deploy.env、compose.yaml 和 manifest 均通过 `SHA256SUMS` 校验。
- 服务器从 `8d529298` 快进到 `5c020561`，随后只重建 backend 和 web；MySQL/Redis 容器和四类数据卷没有重建。
- backend 启动日志确认执行 `0025_quota_policy_v2 -> 0026_stage22_runtime_contract`，四容器最终均为 healthy。
- 公网 HTTP 返回 308 到 HTTPS；HTTPS `/api/v1/health` 返回200；未登录 `/api/v1/conversations` 返回401。
- 线上服务的 JS/CSS SHA-256 与本地 `frontend/dist` 匹配：`index-DjpPtGBX.js`、`index-LYaCnDip.css`。
- 发布前后核心数量不变：users 14、conversations 9、messages 150、documents 27、agent_threads 6、agent_messages 58。
- 发布后的 backend/web 日志没有 traceback、exception、critical 或 error。
- 本次没有调用真实 Qwen、Embedding、Reranker 或 SMTP；额度策略保持 shadow，自动记忆提取保持关闭。

## 4. 工作区与安全边界

- 当前分支 `main` 已推送本次修复；工作区只剩 `backend/app/modules/auth/service.py` 的既有用户修改，禁止修改、格式化、暂存、提交或回退。
- 受保护文件当前 SHA-256 为 `9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0`。
- 不读取或提交 `.env`、SMTP 授权码、API Key、上传文件、Chroma 数据、日志或数据库备份。
- 生产服务器工作区已同步指定提交；`frontend/dist` 是构建输入，不作为源代码提交。

## 5. Stage 23 发布状态

Stage 23 已完成实现、无费用验证和生产发布：

- 新增 ConversationRecoveryService，只将超过 900 秒的 RAG assistant/pending 消息收敛为 failed。
- 新鲜 pending、completed、failed、stopped 和用户消息保持不变；恢复后会话为 idle、最后消息为 failed，并保持未读。
- 会话 API 首次访问时执行一次恢复；没有后台定时器、没有数据库迁移、没有删除文件或向量。
- 配置校验保证恢复阈值大于生成锁 TTL 与清理收尾窗口，Compose 和 .env 示例已同步。
- Agent 继续使用既有 AgentRecoveryService；stopping 仍不单独持久化。
- 新增 5 项临时 SQLite 测试通过；全量后端回归基线 473 项通过，加上本阶段入口测试为 474 项，会话 CRUD/问答/SSE、停止/幂等、生成锁和模型重试回归通过。
- 发布提交为 684e4c1；完整备份位于
  /home/deploy/medical-rag-backups/backup-20260803T143105Z，全部 SHA-256 校验通过。
- 服务器只重建 backend，MySQL、Redis、Web 和命名卷未重建；四容器健康。
- HTTP 308、HTTPS 健康 200、未授权会话 401、900 秒实际配置和错误日志检查通过。
- 未调用 Qwen、Embedding、Reranker 或 SMTP，未创建生产测试数据。

## 6. 新任务阅读范围

新开发窗口先完整阅读 `AGENTS.md` 和本文件。若执行 24.2，只读
`docs/stage24-document-intelligence-and-stability-design.md` 的 1、2、3、4、9、10、11 节，
再定向读取 `knowledge` 解析契约、上传白名单、MIME/签名校验、资料提交、审核预览、
前端上传提示和相关测试。不要读取历史 RAG 评估 JSON，不调用真实模型，不读取真实密钥，
不修改受保护 auth Service。

## 7. 唯一下一任务

**执行 Stage 24.2 DOCX、Markdown、HTML 与网页快照导入。**

先实现本地 DOCX、Markdown、HTML 文件解析，再实现带 SSRF 防护的 URL 抓取与不可变
网页快照。必须复用 24.1 的 normalized parser 契约和 ParserRegistry，更新上传白名单、
MIME/签名校验、审核预览和前端接受格式提示。不得触发 Embedding，不发布真实资料；
真实网页抓取、生产导入或任何外网/内网边界验证都必须先做无副作用预检并取得当次确认。

工作区中的 `backend/app/modules/auth/service.py` 仍是受保护的用户改动，哈希应保持为
`9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0`。禁止修改、
格式化、暂存、提交、回退或覆盖；如需判断来源，只使用 Git 元数据，不读取正文。
