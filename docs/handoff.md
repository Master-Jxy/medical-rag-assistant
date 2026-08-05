# 当前开发交接

> 最后更新：2026-08-06
> 本文件只保留当前事实、工作区边界和一个下一任务。

## 1. 当前真实状态

Stage 24.2 已完成本地开发与无模型验证，未部署、未调用真实模型、Embedding 或生产网络。
24.2a 只实现 DOCX、Markdown、HTML 本地文件支持并保留 PDF/TXT：在
`knowledge` 模块内新增统一 `FileTypePolicy`，普通资料提交和管理员 lifecycle 共用同一套
后缀与内容校验；PDF 校验魔数，DOCX 校验 ZIP/OOXML 必要条目并拒绝宏和外部关系，
TXT/Markdown/HTML 拒绝 NUL 并要求 UTF-8，客户端 MIME 只作为辅助信号。

24.2a 复用 24.1 的 `ParseRequest`、`ParsedDocument`、`ParsedElement`、`ParseQuality`、
`DocumentParserPort` 和 `ParserRegistry`。新增轻量本地 parser adapter：DOCX 输出标题、
段落、列表与表格，Markdown 保留标题/段落/列表/表格语义，HTML 删除 script/style/form/
iframe/object/embed/noscript 等非正文或危险节点后输出标题、段落、列表与表格，不执行任何
内容。发布 lifecycle 将 `ParsedDocument.elements` 转换为现有 LangChain `Document`/切片
输入，并保留 document_id、file_name、source/hash、visibility、document_type 和
knowledge_base_version 元数据；PDF/TXT 切片和引用行为保持回归通过。

本次锁定轻量依赖并记录用途/许可：`python-docx==1.2.0`（MIT，用于 DOCX 结构读取）、
`markdown-it-py==4.2.0`（MIT classifier，用于 Markdown token 化）、`beautifulsoup4==4.15.0`
（MIT，用于 HTML 正文清洗）。未引入 Docling、MinerU、OCR、视觉、网页 URL 抓取、元数据
模型、数据库迁移、API 响应变更或生产配置变更。

24.2a 安全补丁已完成：DOCX ZIP 在读取任何 entry 内容前限制 entry 数量、单 entry
未压缩大小、总未压缩大小、压缩比、加密 entry、重复和异常路径，并在读取 `.rels` 前限制
关系文件大小；外部关系改为在大小限制之后用 XML 结构解析识别任意 `TargetMode=External`，
畸形关系 XML 明确拒绝。HTML 已发布原文预览不再以同源 `text/html` 内联返回，而是
`text/plain; charset=utf-8` 加 `X-Content-Type-Options: nosniff`；当前前端没有渲染
`ParsedElement.table_html`，后续若展示必须继续避免未消毒 `v-html`。

24.2b 受控网页快照已经完成：登录用户通过“导入网页”提交 URL，后端经
`WebSnapshotFetchPort`/httpx infrastructure adapter 安全抓取一次，保存 UUID 命名的不可变
`.html` 快照到 submission 隔离目录，生成内容 SHA-256 并进入现有 pending_review；管理员
审核发布后继续按 HTML parser 切片入公共知识库。RAG/Agent 问答时只读已发布本地快照，
绝不实时访问网页。

网页快照安全边界：仅 http/https，拒绝 userinfo、IP literal、localhost、非默认端口和超长
URL，fragment 在规范化时丢弃，主机名 IDNA 规范化；DNS 任一结果为 loopback/private/
link-local/multicast/reserved/unspecified 均拒绝，每次重定向都重新校验，最多 3 次。响应按
解压后流式读取，最大 3 MB，只接受 text/html/text/plain，拒绝下载、缺失/错误 MIME、空正文、
NUL 和非 UTF-8；text/plain 会转成受控 HTML 快照。由于当前 httpx 常规用法不能可靠做到
“连接固定到已验证 IP 且保持正确 Host/SNI”，生产 adapter 默认关闭，并要求配置域名 allowlist
后才可启用；DNS 重绑定作为残余风险记录，不声称已完全解决。

24.2b 迁移 `0027_web_snapshot_submissions` 为 `knowledge_submissions` 增加可空快照元数据：
original_url、final_url、fetched_at、response_mime、content_sha256。参考 RAGFlow 任务状态
可见性和 Unstructured HTML partition 思想，没有复制源码，没有引入真实网络测试或新重型依赖。

24.1 借鉴边界：Docling 的统一转换出口思想、Unstructured 的统一 Element 模型、Haystack
的 Converter/Splitter 组件分层；没有复制第三方源码，也没有把第三方对象传入业务服务。
24.2a 继续借鉴 Unstructured file partition 与 Haystack converter/splitter 的组件边界；
没有复制第三方源码，也没有让第三方对象泄漏到应用服务。

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
backend\.venv\Scripts\python.exe -m pytest -q backend\tests\test_document_parser_contract.py backend\tests\test_knowledge_submissions_api.py backend\tests\test_admin_reviews_api.py backend\tests\test_admin_document_api.py backend\tests\test_document_service.py
28 passed, 2 warnings

backend\.venv\Scripts\python.exe -m pytest -q backend\tests\test_document_parser_contract.py backend\tests\test_knowledge_trace_api.py
12 passed, 2 warnings

backend\.venv\Scripts\python.exe -m pytest -q backend\tests\test_web_snapshot_fetcher.py backend\tests\test_knowledge_submissions_api.py backend\tests\test_admin_reviews_api.py backend\tests\test_migrations.py
34 passed, 117 warnings

backend\.venv\Scripts\python.exe -m pytest -q backend/tests
505 passed, 120 warnings

D:\Nodejs\npm.cmd --prefix frontend test -- KnowledgeView.test.js AdminAssetsView.test.js
2 files / 5 tests passed

D:\Nodejs\npm.cmd --prefix frontend test
18 files / 74 tests passed

D:\Nodejs\npm.cmd --prefix frontend run test:stream
SSE parser test passed

D:\Nodejs\npm.cmd --prefix frontend run build
Vite production build passed
assets: index-DjFGRvws.css / index-C7p2zpu-.js

backend\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini heads
0027_web_snapshot_submissions (head)

backend\.venv\Scripts\python.exe backend\scripts\import_documents.py --help
passed; help lists supported PDF/TXT/DOCX/Markdown/HTML files

git diff --check
passed

Protected auth hash
9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0
```

Stage 24.0 未做生产数据写入或线上生成验证。当前仓库没有安全、明确的真实公网 IP/SSH
目标可用于本任务的只读生产连接，因此生产健康、容器、迁移、静态资源和错误计数检查
本轮跳过；禁止猜测连接信息。未调用 Qwen、Embedding、Reranker、OCR、视觉或 SMTP。
Stage 24.2 没有执行生产数据操作、生产健康检查、真实网页抓取或任何外网/内网边界验证；
测试 fixture 均为本地生成的非医学资料，网络与 DNS 全部使用 Fake/stub。

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

新开发窗口先完整阅读 `AGENTS.md` 和本文件。若执行 24.3，只读
`docs/stage24-document-intelligence-and-stability-design.md` 的 1、2、3、4、5、9、10、11 节，
再定向读取 `knowledge` 解析契约、PDF parser、复杂 PDF 候选、审核发布生命周期和相关测试。
不要读取历史 RAG 评估 JSON，不调用真实模型，不读取真实密钥，不修改受保护 auth Service。

## 7. 唯一下一任务

**执行 Stage 24.3 复杂 PDF 候选。**

在 24.1/24.2 解析契约基础上，实现复杂 PDF 的 Docling 候选、表格/页码/图片资产输出与
固定集比较；不满足严格门槛时继续使用 PyPDF。不得启用 OCR/视觉真实调用，不触发真实
Embedding，不导入生产资料；任何真实模型、生产导入或线上验证都必须先做无副作用预检并
取得当次确认。

工作区中的 `backend/app/modules/auth/service.py` 仍是受保护的用户改动，哈希应保持为
`9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0`。禁止修改、
格式化、暂存、提交、回退或覆盖；如需判断来源，只使用 Git 元数据，不读取正文。
