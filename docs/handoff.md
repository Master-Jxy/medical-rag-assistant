# 当前开发交接

> 最后更新：2026-08-06
> 本文件只保留当前事实、工作区边界和一个下一任务。

## 1. 当前真实状态

Stage 24.6 重复、版本与失效治理已完成 hardening follow-up 本地实现，等待独立验收；暂不进入 24.7。未部署、未推送，未调用真实 Qwen、Embedding、Reranker、OCR、Vision、SMTP、Docling 或生产网络/数据。

24.6 当前语义：

- 重复信号严格分三层：原始文件 bytes SHA-256 是 exact duplicate，继续通过既有上传/提交去重阻止明显重复；`normalized_text_sha256_v1` 是规范化正文 SHA-256；`simhash64_v1` 是近重复提示，阈值为 Hamming distance <= 8。三者在 API 中以 `exact`、`normalized`、`near` 分开展示，不合并成布尔值。
- `knowledge_submissions` 记录提交阶段规范化正文 hash、近重复 fingerprint、算法版本、显式 duplicate decision 和可选目标 document。普通批准表示继续作为新资料；`POST /admin/reviews/{id}/approve-as-version` 才会显式关联旧资料并作为新版本发布；拒绝仍走既有审核拒绝。
- `document_versions` 新增 `supersedes_document_id`、`change_reason`、`parser_version`、`corpus_version`、规范化 hash 和近重复 fingerprint。新版本同时保留 `replaces_document_id` 兼容既有替换语义；唯一约束防止同一 superseded 文档出现重复 version number。
- 失效治理由 `DuplicatePolicy.governance_status()` 集中计算 `current/due/in_review/expired`。资产列表支持 due/expired/current 筛选，管理员可完成复核、延后复核、标记失效和恢复有效，均写 audit。
- hardening 已建立 RAG/Agent 共用检索资格边界：SearchPort 结果会受控 overfetch，并通过 MySQL 批量确认只返回 `published/ready` 且治理状态非 `expired` 的资料；`archived/failed`、显式 expired、`expires_at` 到时资料不会作为 RAG/Agent 上下文返回，公共知识目录读取同样遵守该语义。
- 现有 `/admin/knowledge-assets/governance/scan` 继续复用 `JobPort`：只为未失效的 due/current 资料创建到期复核任务，expired 保持 expired；对缺少正文指纹的已发布/归档版本做本地解析回填时按 100 条批次上限执行并返回 `remaining` 供幂等重试。任务可观察、失败不改变已发布资料内容或 Chroma。
- near duplicate 查询已有 500 条确定性 SQL 扫描上限、批量页面候选已有 1000 条上限并容错无效 SimHash；资产列表重复候选按当前页批量预取，不再对每条资产重复查库。`restore_current` 会拒绝不晚于当前时间的 `next_review_due_at`。`approve_as_version` 已补失败回滚测试，覆盖旧文档状态/向量恢复、新文档清理和 submission/job 失败状态。
- 后台审核页显示重复候选并提供“作为新版本发布”；知识资产页显示重复提示、版本 lineage、parser/corpus version、治理状态筛选和操作。保持中文企业后台风格，没有新增大页面。
- 本阶段只使用 Python 标准库和已有依赖，没有安装大型依赖；只参考 RAGFlow、Dify、Unstructured、Docling、Haystack 的治理边界思想，没有复制第三方源码。

24.1-24.5 状态保持不变：解析契约、本地多格式、受控网页快照、未晋级 Docling 候选、OCR/Vision Port+Fake、元数据治理均保持默认无真实供应商边界运行。

## 2. 本地验证结果

已通过的 24.6 / hardening 验证：

```text
backend\.venv\Scripts\python.exe -m py_compile backend\app\modules\knowledge\deduplication.py backend\app\modules\knowledge\models.py backend\app\modules\knowledge\submission_service.py backend\app\modules\knowledge\lifecycle.py backend\app\modules\knowledge\review_service.py backend\app\modules\knowledge\asset_service.py backend\app\api\admin_reviews.py backend\app\api\admin_knowledge_assets.py backend\app\modules\knowledge\asset_schemas.py backend\app\modules\knowledge\review_schemas.py backend\app\modules\knowledge\governance_service.py backend\app\services\admin_document_service.py
passed

backend\.venv\Scripts\python.exe -m pytest -q backend\tests\test_stage24_deduplication_policy.py backend\tests\test_admin_reviews_api.py backend\tests\test_admin_knowledge_assets_api.py backend\tests\test_admin_document_service.py backend\tests\test_admin_document_api.py backend\tests\test_knowledge_submissions_api.py backend\tests\test_migrations.py
52 passed, 137 warnings

D:\Nodejs\npm.cmd --prefix frontend test -- AdminReviewsView.test.js AdminAssetsView.test.js
2 files / 7 tests passed

backend\.venv\Scripts\python.exe -m pytest -q backend\tests
595 passed, 1 skipped, 140 warnings

D:\Nodejs\npm.cmd --prefix frontend test
19 files / 79 tests passed

D:\Nodejs\npm.cmd --prefix frontend run test:stream
SSE parser test passed

D:\Nodejs\npm.cmd --prefix frontend run build
Vite production build passed
assets: index-DlOXPwXa.css / index-CGLlwHMM.js

backend\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini heads
0029_dedup_version_governance (head)

Alembic 临时 SQLite roundtrip
upgrade head -> downgrade 0028_metadata_suggestions -> upgrade head passed

Protected auth hash
9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0
```

本轮 hardening 已通过的聚焦验证：

```text
backend\.venv\Scripts\python.exe -m py_compile backend\app\modules\knowledge\retrieval_eligibility.py backend\app\services\rag_service.py backend\app\modules\agent\runtime.py backend\app\modules\knowledge\public_catalog.py backend\app\modules\knowledge\deduplication.py backend\app\modules\knowledge\asset_service.py backend\app\modules\knowledge\governance_service.py backend\tests\test_rag_ports.py backend\tests\test_stage24_deduplication_policy.py backend\tests\test_admin_knowledge_assets_api.py backend\tests\test_admin_reviews_api.py
passed

backend\.venv\Scripts\python.exe -m pytest -q backend\tests\test_rag_ports.py backend\tests\test_agent_knowledge_tools.py backend\tests\test_stage24_deduplication_policy.py backend\tests\test_admin_knowledge_assets_api.py backend\tests\test_admin_reviews_api.py
36 passed, 2 warnings

backend\.venv\Scripts\python.exe -m pytest -q backend\tests
595 passed, 1 skipped, 140 warnings

D:\Nodejs\npm.cmd --prefix frontend test
19 files / 79 tests passed

D:\Nodejs\npm.cmd --prefix frontend run test:stream
SSE parser test passed

D:\Nodejs\npm.cmd --prefix frontend run build
Vite production build passed
assets: index-DlOXPwXa.css / index-CGLlwHMM.js

backend\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini heads
0029_dedup_version_governance (head)

Alembic 临时 SQLite roundtrip
upgrade head -> downgrade 0028_metadata_suggestions -> upgrade head passed
```

hardening 提交前最终检查已完成：`git diff --check` 通过（仅受保护 auth 工作区 LF/CRLF 提示，不是 whitespace error，且 auth 未暂存）；`git diff --cached --check` 通过；前端审核/资产页及测试按 UTF-8 解码且不含 U+FFFD；显式 staged 列表已核对且不包含 `backend/app/modules/auth/service.py`；最终受保护 auth SHA-256 仍为 `9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0`。

未执行项：未做生产健康/容器/迁移/静态资源/错误计数检查；本阶段不做生产操作。

## 3. 工作区与安全边界

- 当前分支：`main`。
- 本任务只允许本地提交，不推送、不部署。
- `backend/app/modules/auth/service.py` 是受保护用户改动，禁止读取正文、修改、格式化、暂存、提交、回退或覆盖。目标 SHA-256 必须保持：
  `9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0`。
- 不读取 `.env`、真实上传资料、Chroma 数据、数据库备份或正文日志。

## 4. 新任务阅读范围

新窗口先完整阅读 `AGENTS.md` 和本文件。若执行唯一下一任务，只读：

- `docs/stage24-document-intelligence-and-stability-design.md` 中 24.6、安全、验收相关段落。
- `docs/technical-design.md` 的 Stage 24.6 Duplicate, Version, and Expiry Governance Boundary 及 hardening 段落。
- `docs/stage24-open-source-benchmark.md` 的 Stage 24.6 adopted references。
- 直接相关源码/测试：`knowledge/retrieval_eligibility.py`、`knowledge/deduplication.py`、`models.py`、`submission_service.py`、`review_service.py`、`asset_service.py`、`governance_service.py`、`public_catalog.py`、`rag_service.py`、`agent/runtime.py`、`lifecycle.py`、`admin_reviews.py`、`admin_knowledge_assets.py`、`AdminReviewsView.vue`、`AdminAssetsView.vue` 及对应测试。

不要进入 24.7，不读取历史 RAG 评估大型 JSON，不触碰受保护 auth 文件。

## 5. 唯一下一任务

**执行 Stage 24.6 hardening 独立验收。**

只复核 exact/normalized/near 信号分离、规范化算法版本与资源上限、近重复阈值、审核重复候选、作为新版本发布、版本防环/并发、due/expired 治理筛选、JobPort 扫描幂等、迁移往返、中文前端交互和回归测试；通过后再由后续任务决定是否放行 24.7。
