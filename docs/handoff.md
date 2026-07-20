# 当前开发交接

> 最后更新：2026-07-21
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
- `corpus_v1` 版本化语料清单、只读一致性审计，以及未来 30～50 题使用的 `evaluation_set_v1` 数据契约和分类配额。
- 基于27份真实本地原文的40题 `eval_v1`、静态校验器和人工审查清单；28道回答题覆盖全部27份文档，12道拒答题不登记来源。
- `eval_v1` 与 `corpus_v1` checksum 强绑定；离线基线 Runner、检索/回答 Port、版本化报告契约、假适配器干跑，以及当前 Chroma/Qwen 的只读真实适配器和付费运行闸门。
- 两次受控40题真实基线、Git忽略且7天过期的回答捕获，以及不含正文的逐题人工决定和差异摘要；原始基线报告保持不变。
- `RagService` 对外入口不变，内部已拆为查询构造、知识检索、回答生成三个稳定Port；当前适配器保持冻结的Prompt、Chroma和Qwen行为。
- `KnowledgeSearchPort` 已支持默认关闭的科室/主题/文档类型/知识库版本过滤和最低相关度；无合格片段时三类问答统一拒答且不调用模型。
- 默认关闭的关键词+向量混合检索：独立关键词Port、本地BM25式排序、加权RRF融合、片段去重和关键词故障向量回退。
- 默认关闭的独立重排阶段：`RerankPort`、DashScope薄适配器、候选/Token/费用/超时硬边界、单次调用计量，以及超预算或失败时原候选顺序回退。
- 已冻结的RAG v1.2：三套完整配置指纹、同一`eval_v1`真实对比、分阶段质量/耗时/费用、全局预算和双重确认闸门；真实结果未证明混合检索或Reranker提高来源指标，因此生产继续使用向量基线，两项实验能力保持默认关闭。
- 任务7.7第一小步：无I/O候选池策略固定候选12、每文档最多2片段、最终4片段；独立排序报告登记四套完整Profile与配置指纹，逐题/分类/总体计算文档级`Recall@4/10`、完整命中、`MRR@4`、`nDCG@4`、唯一文档数和重复率，确定性Mock报告不含正文且不代表真实收益。
- 任务7.7：共享输入只读排序、版本化计划、失败审计与恢复闸门均已完成；有效40题运行没有候选达到预登记晋级门槛，生产继续保留向量基线且不运行Qwen完整回答评估。
- 任务7.8：本地发布范围、敏感文件、报告正文、依赖、迁移、语料和完整测试审计通过；用户确认后已按清单完成暂存复核、单一RAG v1.2.1里程碑提交和GitHub推送，服务器尚未更新。

2026-07-17 已在任务 6.4b 完成后的真实代码和页面验收基础上同步状态，`RAG v1.1` 已冻结。项目继续采用**模块化单体**，不拆微服务；后续开发固定沿着“Router -> Application Service -> Port -> Adapter”的方向增量演进。RAG、Agent、认证、知识库和会话拥有独立模块边界，Agent 不替换普通 RAG，也不能直接访问 Repository、Chroma、Redis 客户端或系统命令。

当前尚未实现：

- 任务7.8的服务器里程碑同步。
- 结构化监控页面。
- 独立 Agent 模块。
- HTTPS/域名、自动备份和云端上传/问答/重启恢复完整验收。

部署基线已于 2026-07-17 完成：仓库具备 MySQL、Redis、FastAPI、Vue/Nginx 的 Compose 编排、持久卷、健康检查和资源上限，并已在 Ubuntu 22.04、2 核 2G 阿里云 ECS 上通过公网首页、健康接口、注册、登录、当前用户、创建会话和文档列表验收。公网 HTTP 环境不提供原生 `crypto.randomUUID()`，前端统一 UUID 工具会优先使用原生实现，并在 HTTP/旧浏览器中安全降级，保证聊天临时消息和幂等键可以生成。当前仅开放 HTTP，真实账号不得复用其他网站密码；部署和更新命令以 `docs/deployment.md` 为准。

目标演进顺序已经固定为：

```text
Redis 接口保护
-> RAG 评估与检索优化
-> 候选池补充实验与RAG v1.2.1里程碑发布
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
- 离线评估契约与语料清单：`backend/app/evaluation/`、`backend/evaluation/`
- `corpus_v1` 只读生成与复核：`backend/scripts/build_corpus_manifest.py`
- `eval_v1` 静态校验：`backend/app/evaluation/validation.py`、`backend/scripts/validate_evaluation_set.py`
- 评估题与人工审查清单：`backend/evaluation/datasets/eval_v1.json`、`backend/evaluation/reviews/eval_v1_review.md`
- 离线 Runner 与 Port：`backend/app/evaluation/runner.py`、`backend/app/evaluation/ports.py`
- 报告契约和假适配器：`backend/app/evaluation/report_schemas.py`、`backend/app/evaluation/fake_adapters.py`
- 可重复干跑：`backend/scripts/run_fake_evaluation.py`、`backend/evaluation/reports/dry_run_v1.json`
- 人工复核契约与解释性评分：`backend/app/evaluation/human_review.py`、`backend/app/evaluation/review_scoring.py`
- 受控捕获与决定应用：`backend/app/evaluation/review_capture.py`、`backend/scripts/run_human_review_capture.py`、`backend/scripts/apply_local_human_review_decisions.py`
- 本地复核校验命令：`backend/scripts/validate_local_human_review.py`；回答正文目录 `backend/evaluation/local_reviews/` 被 Git 忽略且最多保留7天。
- 无正文复核产物：`backend/evaluation/reviews/human_review_capture_v1_decisions.json`、`backend/evaluation/reviews/human_review_capture_v1_summary.md`
- RAG内部Port与当前适配器：`backend/app/modules/rag/ports.py`、`backend/app/modules/rag/adapters.py`
- RAG检索与拒答策略：`backend/app/modules/rag/policies.py`
- 关键词检索与混合融合：`backend/app/modules/rag/keyword_search.py`、`backend/app/modules/rag/hybrid_search.py`
- 重排Port、策略和阶段编排：`backend/app/modules/rag/ports.py`、`backend/app/modules/rag/policies.py`、`backend/app/modules/rag/rerank.py`
- DashScope重排基础设施适配器：`backend/app/infrastructure/reranker.py`
- RAG统一编排入口：`backend/app/services/rag_service.py`
- RAG候选对比契约与Mock编排：`backend/app/evaluation/comparison_schemas.py`、`backend/app/evaluation/comparison.py`
- 候选池纯策略与排序指标：`backend/app/modules/rag/candidate_selection.py`、`backend/app/evaluation/retrieval_ranking.py`
- 排序报告契约、Schema和Mock报告：`backend/app/evaluation/retrieval_ranking_schemas.py`、`backend/evaluation/schemas/retrieval_ranking_report_v1.schema.json`、`backend/evaluation/reports/retrieval_ranking_mock_v1.json`
- 纯本地对比计划：`backend/app/evaluation/comparison_preflight.py`、`backend/evaluation/plans/rag_v1_2_preflight_v1.json`
- Mock对比报告：`backend/evaluation/reports/rag_v1_2_mock_comparison_v1.json`

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

截至 2026-07-18：

- 原 36 份短文档已通过共享文档生命周期全部删除；替换前数据库与存储备份位于 `backend/backups/before_knowledge_refresh_20260717_012243/`。
- MySQL 公共系统文档数：27；全部来自桌面“医疗文档”目录，上传者均为空，普通用户不可删除。
- Chroma 文本片段数：103；MySQL 登记片段 ID、Chroma 数量和磁盘文件已逐项核对一致。
- 27 份源文件与入库记录的 SHA-256 全部一致，无缺失文件、未知登记或临时删除文件。
- 当前语料已登记为 `backend/evaluation/corpora/corpus_v1.json`：只保存文档/片段 ID、文件名、大小、字符数和 SHA-256，不复制正文；清单总校验值为 `f97a8befb45f8f85136a3205ffcde15b739b13b6a23d4050e9c6c34ddd440d9a`。
- `corpus_v1` 只读审计确认 MySQL、磁盘与 Chroma 双向一致，无重复文件哈希、重复片段正文、空文档或空片段；存在 1 个 17 字符的短尾片段 `012c35e6-4cee-4498-b6e0-c0985f8781ac:6`，作为非阻断质量提示保留，本步未重切或删除。
- `eval_v1` 共40题：单文档14、多文档8、连续追问6、知识不足8、安全边界4；题目来自上述27份本地原文。28道回答题的期望来源覆盖27/27份文档，12道拒答题来源为空；人工核对入口为 `backend/evaluation/reviews/eval_v1_review.md`。
- `eval_v1.corpus_checksum` 与 `corpus_v1` 当前值完全一致；checksum 不一致会在任何检索或回答适配器调用前失败。
- `dry_run_v1` 使用假适配器完成38题并固定注入2个失败，37题有Token/费用计量、1题计量缺失，费用完整性为否。来源召回、拒答准确率和关键事实覆盖率均为1.0只表示假适配器编排正确，不代表真实RAG质量。
- `current_baseline_v1.json` 原始报告保持不变，SHA-256 为 `598952A8772FDE26EAC428CDAD0335F889241F61D12B9C55BFABED5329A26ED5`。
- `human_review_capture_v1.json` 完成40题、0失败，来源平均召回率0.919643、完整来源命中率0.785714；计量为70158输入、9735输出、79893总Token，Qwen估算0.272745元，报告 SHA-256 为 `DB4A9AFC6ED4404A17512DCF5AC39017BF3FB64CF6B8DA06DC874C416B6F0A84`。
- 人工复核把行为准确率从自动0.8修正为1.0、12道拒答题从0.333333修正为1.0；36道无不确定项题目的平均事实覆盖从自动0修正为0.916667，事实项共95满足、9未满足、4不确定。该结论不代表额外事实都忠实或拒答后绝无危险细节。
- 回答正文仅在 Git 忽略的 `backend/evaluation/local_reviews/human_review_capture_v1.json`，北京时间2026-07-25 20:57:34到期；版本化决定和摘要不包含回答正文。
- 替换前数据库备份 `medical_rag.sql` 的 SHA-256：`BBA0638CE118AFA4A66E194B674915FC163A20F4F17E372E6D830598ACB1B057`。
- 替换前文件与 Chroma 备份 `knowledge_storage.zip` 的 SHA-256：`48E0B88795B50EAA9D50BE321715F4CC1303F4FD6C4F90DDE90F39A55BF779DA`。
- `backend/scripts/import_documents.py` 通过系统文档生命周期批量导入，要求 `--confirm` 且重复内容幂等跳过；`backend/scripts/migrate_document_registry.py` 负责旧 JSON 登记的一次性幂等迁移。
- MySQL 迁移版本：`0005_user_role`；现有 2 个账号均保持普通用户角色。
- 当前用户、会话、消息、引用数量：3、2、22、28；这是现有正常数据，不得作为临时数据清理。40道评估问题在消息表中的匹配数为0，真实基线没有写入这些业务数据。
- 迁移前备份：`backend/backups/before_auth_migration_20260715_010920.sql`（被 Git 忽略）。
- 会话归属迁移备份：`backend/backups/before_conversation_ownership_20260715_014819.sql`（被 Git 忽略）。
- 文档迁移前数据库备份：`backend/backups/before_document_registry_20260715_022247.sql`（被 Git 忽略）。
- 文档迁移前文件、旧 JSON 和 Chroma 备份：`backend/backups/before_document_storage_20260715_022247.zip`（被 Git 忽略，SHA-256：`B7CCFB1CB5F0E48A0A62097AF09848DDA2417D678157CD24348423191421C32E`）。
- 管理员迁移前数据库备份：`backend/backups/before_admin_20260715_130405.sql`（被 Git 忽略，SHA-256：`88956B936B9C67AF81AB20965300A1E6B6BB3A8D57BE5F4A5AE9C04636C09512`）。
- 管理员迁移前文件和 Chroma 备份：`backend/backups/before_admin_storage_20260715_130405.zip`（被 Git 忽略，SHA-256：`CD723C81E9EF50B85EDFEF5AE3B106D8EE20EEF702876093284EF8CFB1D0B10C`）。

这是本地快照，不应硬编码到页面或业务逻辑。迁移脚本可重复运行，已导入登记会被跳过，也不会重新调用 Embedding。

## 6. 当前工作区注意事项

任务7.1～7.7的评估产物、候选策略、RAG Port、过滤/阈值、混合检索、Reranker、真实报告、测试和文档已作为单一RAG v1.2.1里程碑发布。服务器同步前不得改写该发布证据或把本地运行时数据纳入Git。

新任务不得执行 `git reset --hard`、`git checkout --` 或批量清理未跟踪文件。开始编码前必须查看 `git status` 和与当前任务相关的 diff，只在现有实现上继续；遇到其他窗口刚产生的变化时，以代码和测试为准并同步文档。

## 7. 最近一次完整验证

2026-07-21 任务7.7有效恢复运行完成后的最近验证：

- `CandidateSelectionPolicy`只接收统一 `RetrievedChunk`：稳定截取12个候选，按非空文档ID最多保留2片段，最终取4；未知文档按输入位置分别计数。代码只被评估模块、Mock脚本和测试引用，`RagService`、API与生产配置没有接入。
- `retrieval_ranking_report_v1` 固定四套Profile及唯一SHA-256配置指纹，绑定同一 `eval_v1` 与 `corpus_v1` checksum；40题逐题结果按14/8/6/8/4分类汇总，28道有来源题参与排序平均，12道空来源题的八项指标全部为 `null`。
- 可重复 `retrieval_ranking_mock_v1.json` 和Schema生成通过；报告不含问题、回答、Prompt、文件名、`content`或`page_content`。Mock中人为构造的质量差异只验证文档配额和指标算术，没有读取真实Chroma、Embedding、Reranker、Qwen或MySQL，没有产生费用。
- 三份冻结报告哈希保持不变：当前基线 `598952A8772FDE26EAC428CDAD0335F889241F61D12B9C55BFABED5329A26ED5`、人工捕获 `DB4A9AFC6ED4404A17512DCF5AC39017BF3FB64CF6B8DA06DC874C416B6F0A84`、RAG v1.2真实对比 `F54E86A1B39518D998E861C101B225B160188D373488BCA4FA821913C09E2893`；生产混合检索和Reranker仍为关闭。
- 共享真实排序适配器的Mock证明：每题四套候选合计只调用一次向量检索、一次本地关键词扫描，且仅第四套最多调用一次Reranker；关键词或Reranker失败不重试并回退，预算不足在外部调用前停止。真实执行模块不导入Qwen、会话Service或数据库写入能力。
- 无费用完整预检通过：40题、27份文档、103个Chroma片段、`corpus_v1`快照、四份冻结报告哈希、四套配置指纹、生产实验开关关闭和DashScope密钥存在性均一致；未创建远程客户端、未联网验证密钥权限。计划SHA-256为 `e5dad0f67cf981695e16ac8724f33b1494ed1667a336a82c62039fd876ac6c53`。
- 真实排序预算：最多40次Embedding、40次本地关键词扫描、40次Reranker、0次Qwen，最多1220480 Token、预计0.2～0.6元、费用硬上限1.1元，自动重试0。第二小步没有运行真实Embedding/Reranker/Qwen，没有生成正式真实排序报告或产生费用。
- 用户确认后首次执行真实排序：40题关键词扫描和Reranker成功，向量阶段因真实对象缺少`search`方法全部在Embedding调用前本地失败。Reranker共40次、246713输入Token、估算0.1973704元；无效报告保守总估算0.20761元另含未实际调用的Embedding预留。四套排序指标无可比性，禁止晋级。
- 无效JSON已保留为`retrieval_ranking_real_v1_invalid_vector_port_20260721.json`，SHA-256为`E2396F97CA5F5F6E89C2BFB9C6E53A5E9EC064CE2135371C928A4028836ACD5C`，正式有效报告路径重新空出但禁止无确认重跑。
- 根因已修复：真实工厂通过`CurrentChromaKnowledgeSearchAdapter`包装只读Chroma对象；新增真实装配形状测试和40题向量全失败时拒绝发布正式报告的保护。恢复计划完整无费用预检通过，SHA-256为`72B18169399F8805D9384D688585B74250230C4BD3CC38DCED19DFF6B1C012E4`。
- 用户重新确认后有效恢复运行完成：40题向量、关键词和Reranker全部成功，无失败回退或重试，Qwen调用0次；Embedding保守预留20480 Token、Reranker计量176792输入Token，本轮估算0.151674元，两次合计保守估算0.359284元。
- 正式报告SHA-256为`D4BDB8AD0953463C215CFA02EE08125BDE4F7BC8F0ECBA68EB5B036684DBD365`，不含问题、回答、Prompt或文档正文。运行后MySQL仍为27份文档，评估问题在消息表匹配0条，Chroma仍为103片段。
- 晋级结论：`vector_wide_diverse_v1`总体Recall@4从0.919643提高到0.931548，但多文档只提高0.041667，未达到0.05；两个混合方案多文档提高0.072917，但总体降至0.904762，违反总体不回退条件。没有候选晋级，生产混合检索与Reranker继续关闭。
- 任务7.8本地发布审计：审计开始时12个已跟踪修改、91个未跟踪阶段文件；新增`docs/release-audit-rag-v1.2.1.md`后形成完整候选清单。真实`.env`、Chroma、上传文件、备份、本地回答、依赖、构建和缓存目录均被Git忽略；候选强敏感模式与版本化报告正文字段扫描无命中，最大候选文件约235KB。
- 发布环境只读检查通过：`pip check`无冲突，Alembic为`0005_user_role (head)`，本地人工复核包仍在忽略目录、40题绑定有效且2026-07-25到期；当前分支`main`、基准提交`82d1cb94bc3a11bb06ceb833cfbda747d7d1dd52`，暂存区为空。

- 用户在预检后确认0.6～1.0元预计费用和4.4元硬上限；唯一一次真实候选对比正常完成，没有重试或预算停止。冻结向量基线没有重复调用，两个新候选各40题全部成功，正式报告SHA-256为 `F54E86A1B39518D998E861C101B225B160188D373488BCA4FA821913C09E2893`。
- 两个新候选本次合计估算费用0.622606元。`hybrid_rrf_v1` 总费用0.286745元、总平均耗时8059.93ms；`hybrid_rrf_rerank_v1` 总费用0.335861元、总平均耗时8400.74ms，40次Rerank全部成功并使用71745输入Token。Embedding计量使用保守预留，因此该费用是可核验估算值，不冒充账单最终扣费。
- 三套方案的来源平均召回率均为0.919643、完整来源命中率均为0.785714；混合检索没有质量提升而总耗时增加4.50%，增加Reranker仍没有提升且总耗时增加8.92%、Token增加71.01%、费用增加18.65%。自动拒答只多正确 `eval_032` 一题，两个新候选结果相同，无法排除生成波动；结合既有人工复核限制，不把它归因于检索收益。
- 决策：生产继续使用 `vector_baseline_v1`，`RAG_HYBRID_SEARCH_ENABLED=false` 和 `RAG_RERANK_ENABLED=false` 保持不变。实验Port和适配器保留用于可复现测试，不进入当前运行时主链路；RAG v1.2已冻结。
- 正式报告通过 `rag_comparison_report_v1` Schema，且不含问题、回答、Prompt或文档正文。运行后MySQL仍登记27份文档，40道评估问题在消息表中的匹配数为0；语料复核仍为27份文档、103个Chroma片段。

- 两个新候选的只读真实适配器、共享全局预算、分阶段计量和双重确认入口已完成。定向Mock证明两个候选各运行40题、冻结基线不变；单题回答或Rerank失败不重试，保留最坏预留并隔离当前题，成功调用缺失计量或下一次调用无法容纳时停止整轮。
- 完整预检通过：`eval_v1` 40题、当前27份文件、MySQL公共登记、Chroma 103片段、`corpus_v1` checksum、两个冻结报告哈希、三套候选配置、生产优化开关和DashScope密钥存在性均一致；未联网探测权限，未创建远程客户端。计划SHA-256为 `8dc58c5988ae51f0afde5df576e408318082663813a276c5bf9d8b640aa00249`。
- 2026-07-19中国内地公开单价快照：`qwen3-max` 输入/输出每百万Token 2.5/10元，`text-embedding-v4` 输入0.5元，`gte-rerank-v2` 输入0.8元。结合当前基线计量预计两个候选合计约0.6～1.0元；硬停止上限仍为80次Embedding、80次Qwen、40次Rerank、148万Token和4.4元。本步没有执行付费命令，没有产生新的模型费用或正式真实对比报告。

- 后端：222 项通过；新增覆盖同题四候选共享一次向量/关键词输入、仅一次Reranker、零重试、关键词与重排失败回退、预算调用前停止、双重确认、计划防篡改、真实存储必须包装为稳定检索Port、40题向量全失败禁止发布、40题假适配器报告无正文和正式报告禁止覆盖；原候选池、评估Runner、Reranker、混合检索、模型流取消、认证、会话、Redis、文档补偿和管理员测试无回归。
- Vue：8 个测试文件、29 项测试通过，覆盖原登录闭环、文档权限、管理员交互、稳定错误提示、SSE 读取器取消、等待后端停止确认后恢复发送，以及公网 HTTP 环境缺少 `crypto.randomUUID()` 时的兼容 UUID 生成。
- SSE UTF-8 字节分片测试：通过。
- Vite 正式构建：通过。
- `corpus_v1` 生成后再次以 `--check` 只读复核通过：27 份文档、103 个片段，状态 `passed_with_warnings`；JSON 递归检查不存在 `content`、`text`、`page_content` 或 `body` 正文字段。本步未调用真实大模型或 Embedding，未写 MySQL、Chroma 或线上数据。
- `eval_v1` 静态校验通过：40题，分类配额为14/8/6/8/4，来源覆盖27/27且无未覆盖文档；人工审查清单包含40个唯一题号。本步只读取本地原文和版本化 JSON，没有运行 Chroma 检索、真实模型或 Embedding。
- `dry_run_v1` 可重复生成并通过报告 Schema：38题完成、2题按计划失败、37题有计量、1题计量缺失；`estimated_cost_complete=false`。checksum 反向测试确认不一致时两个适配器均不会被调用。本轮仍未运行真实 Chroma、Embedding 或模型，也未写 MySQL 会话。
- `python -m scripts.run_current_baseline` 只读预检通过：当前 MySQL 公共文档登记、27份磁盘文件、Chroma 103片段与 `corpus_v1` 完整一致；`eval_v1` checksum、模型名称、密钥存在性、`top_k=4`、零重试和硬预算均通过。该命令输出 `PRECHECK_ONLY`，未联网验证密钥、未调用真实 Embedding/Qwen、未写 MySQL/Chroma，也未生成 `current_baseline_v1.json`。
- 用户确认后已完成 `current_baseline_v1`：40题完成、0失败，来源平均召回率0.919643、完整来源命中率0.785714、多文档来源召回率0.71875；输入70158 Token、输出9743 Token，Qwen估算费用0.272825元，运行约311秒。报告 SHA-256 为 `598952A8772FDE26EAC428CDAD0335F889241F61D12B9C55BFABED5329A26ED5`。
- 报告不保存问题或回答正文，MySQL消息中40道评估问题匹配数为0，运行后语料仍为27份文档和103个片段。拒答固定文案分类得到0.333333，关键事实整句精确评分得到0；这两项存在评分器误判可能，不能直接宣称模型拒答失败或事实正确率为0，详见 `backend/evaluation/reviews/current_baseline_v1_review.md`。
- 任务7.1第五小步已增加 `local_human_review_v1`：回答正文只能放入 Git 忽略的 `backend/evaluation/local_reviews/`，必须绑定原报告哈希并在最多7天后删除；校验汇总不会输出正文或备注，也不依赖MySQL、Chroma或模型。固定脱敏样例中，替代拒绝措辞由v1的 `answer` 变为v2的 `refuse`，同义事实由v1覆盖0变为人工别名覆盖1；这不是对真实40题的重评分。
- 用户授权后完成独立 `human_review_capture_v1`：40题、0失败、最多40次Embedding和40次Qwen、零自动重试，费用和Token均未触发硬上限；原始报告哈希复核不变。逐题决定已通过报告哈希、语料checksum、题号全集、7天期限和不泄露正文校验。
- 捕获发布遗留问题已修复：报告和本地复核包分别暂存并全部校验后再补偿式发布；第二份暂存写入或第二份正式替换失败时不会留下任一正式产物，启动时只清理固定捕获暂存文件。同名正式产物继续禁止覆盖。
- 任务7.2已把查询构造、知识检索和回答生成拆为三个Port；普通问答、会话问答和SSE继续使用同一个 `RagService`，定向测试覆盖三个接口独立替换、固定空检索拒答、来源结构和同步/异步事件顺序。
- 本轮只运行Mock和本地自动化测试，没有调用真实Qwen或Embedding，没有产生新费用，没有写MySQL、Chroma或线上数据；两个7.1正式报告SHA-256均保持不变，捕获专用暂存文件数量为0。
- 任务7.3已增加四类白名单元数据过滤、可选最低相关度、集中知识不足拒答和新上传片段的文档类型/知识库版本元数据；默认配置关闭过滤和阈值，现有103个片段未回写，Prompt、`top_k`、Embedding和来源格式未改变。
- 任务7.4已增加独立关键词Port和加权RRF融合；默认运行配置关闭混合检索并只组装原向量适配器。关键词失败回退原向量顺序，向量失败继续上抛；本轮没有真实检索、Embedding、Qwen或付费评估。

2026-07-17 任务 6.4b 的真实运行验收仍有效：

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

开始 **任务 7.8 服务器同步：仅在用户单独确认后，把已发布的RAG v1.2.1指定提交同步到演示服务器**。

```text
本地发布审计、暂存复核、单一里程碑提交和GitHub推送已完成。服务器仍运行原版本，本次Git发布没有连接或修改服务器。
```

执行服务器同步前必须：

- 用户在新的操作闸门中明确确认服务器更新，Git发布确认不能自动扩展为服务器操作授权。
- 先读取线上当前提交、容器与数据卷状态，并备份MySQL、Chroma、上传文件和Redis持久数据。
- 服务器只拉取已确认的RAG v1.2.1指定提交，不直接编辑业务代码，不覆盖真实`.env`，不得执行`docker compose down -v`。
- 重建后验证健康、认证、会话、上传、普通与SSE问答、引用、停止生成和重启恢复；失败时回滚代码提交并按需恢复数据。
