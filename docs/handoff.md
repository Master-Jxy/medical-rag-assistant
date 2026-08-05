# 当前开发交接

> 最后更新：2026-08-06
> 本文件只保留当前事实、工作区边界和一个下一任务。

## 1. 当前真实状态

Stage 24.5 元数据治理已完成主实现，并正在进行独立 follow-up 验收修复；暂不放行 24.6。未部署、未推送，未调用真实模型、Embedding、Reranker、OCR、Vision、SMTP、Docling 或生产网络/数据。

24.5 当前语义：

- `metadata_suggestions` 是独立持久化表，正式元数据仍只在管理员接受或编辑确认后写入 `document_versions`。
- `GET /admin/reviews` 与 `GET /admin/reviews/{id}` 必须严格只读：只返回已有 suggestion，不创建、不 flush、不 commit、不写 audit。
- 元数据建议生成是显式管理员写动作：`POST /admin/reviews/{id}/metadata-suggestion/generate`。同一 submission 幂等返回已有记录；并发创建依靠 `submission_id` 唯一约束和事务 rollback 后查询处理，不能泄漏为 500。
- accept/reject 只能操作已存在 suggestion；不存在返回稳定 404。状态迁移使用 `status='suggested' + expected_revision` 原子匹配，新 revision 使用 expected revision + 1，避免 stale ORM 值。
- `metadata_suggestion_mode` 只允许 `disabled` 或 `fake`；未知 mode 在配置/工厂边界失败。`suggestion_source` 只允许受控集合，未知 provider source 归一为安全的 `disabled`。
- generate/accept/reject 的 audit 或 commit 失败必须 rollback，不留下半条 suggestion、状态迁移、正式元数据或 audit 半成品。
- 管理员审核 UI 保持中文审核中心文案；suggestion 为空时显示紧凑空态和“生成建议”按钮；已有 suggestion 才显示建议值、确认值、证据、置信度、warning 以及接受/编辑/拒绝动作。
- `MetadataSuggestionService` 只保留明确读写边界：`get_existing_for_submission(s)` 只读，`generate_for_submission` / `generate` 写入；已删除名称暗示隐式写入的 `get_or_create_for_submission`。审核列表使用 submission_id batch 查询已有 suggestion，避免逐条 N+1。

24.1-24.4 状态保持不变：24.1 解析契约、24.2a 本地 DOCX/Markdown/HTML、24.2b 受控网页快照、24.3 未晋级 Docling 候选、24.4 OCR/Vision Port+Fake+资产生命周期仍按各自默认关闭/无真实供应商边界运行。

开源借鉴记录不变：24.5 参考 Docling、RAGFlow、Unstructured、Dify、Haystack 的解析产物与治理状态分离、人工确认后发布/治理思想；没有复制第三方源码，没有新增依赖。

## 2. 本地验证结果

本 follow-up 已通过的验证：

```text
backend\.venv\Scripts\python.exe -m py_compile backend\app\modules\knowledge\metadata_suggestions.py backend\app\modules\knowledge\review_service.py backend\app\api\admin_reviews.py backend\tests\test_metadata_suggestions.py
passed

backend\.venv\Scripts\python.exe -m pytest -q backend\tests\test_metadata_suggestions.py backend\tests\test_admin_reviews_api.py backend\tests\test_migrations.py
36 passed, 128 warnings

D:\Nodejs\npm.cmd --prefix frontend test -- AdminReviewsView.test.js
1 file / 3 tests passed

backend\.venv\Scripts\python.exe -m pytest -q backend\tests
581 passed, 1 skipped, 131 warnings

D:\Nodejs\npm.cmd --prefix frontend test
19 files / 77 tests passed

D:\Nodejs\npm.cmd --prefix frontend run test:stream
SSE parser test passed

D:\Nodejs\npm.cmd --prefix frontend run build
Vite production build passed
assets: index-MZNRkzde.css / index-pV-bJNjX.js

backend\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini heads
0028_metadata_suggestions (head)

Alembic 临时 SQLite roundtrip
upgrade head -> downgrade 0027_web_snapshot_submissions -> upgrade head passed

Protected auth hash
9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0
```

本轮 follow-up 独立验收补丁已通过：

```text
backend\.venv\Scripts\python.exe -m py_compile backend\app\modules\knowledge\metadata_suggestions.py backend\app\modules\knowledge\review_service.py backend\tests\test_metadata_suggestions.py
passed

backend\.venv\Scripts\python.exe -m pytest -q backend\tests\test_metadata_suggestions.py backend\tests\test_admin_reviews_api.py
22 passed, 2 warnings

D:\Nodejs\npm.cmd --prefix frontend test -- AdminReviewsView.test.js
1 file / 3 tests passed

D:\Nodejs\npm.cmd --prefix frontend test
19 files / 77 tests passed

D:\Nodejs\npm.cmd --prefix frontend run build
Vite production build passed
assets: index-B9neMpJ8.css / index-CnPOegrw.js

Protected auth hash
9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0
```

本轮未重复完整 backend 581 项：后端变更仅删除无调用兼容方法、将审核列表 suggestion 查询改为 batch，并由聚焦 API/service 测试覆盖读写边界和列表行为。

未执行项：未做生产健康/容器/迁移/静态资源/错误计数检查；本阶段不做生产操作。

## 3. 工作区与安全边界

- 当前分支：`main`。
- 本任务只允许本地提交，不推送、不部署。
- `backend/app/modules/auth/service.py` 是受保护用户改动，禁止读取正文、修改、格式化、暂存、提交、回退或覆盖。目标 SHA-256 必须保持：
  `9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0`。
- 不读取 `.env`、真实上传资料、Chroma 数据、数据库备份或正文日志。

## 4. 新任务阅读范围

新窗口先完整阅读 `AGENTS.md` 和本文件。若执行唯一下一任务，只读：

- 8c51f1f 及本 follow-up 中 metadata suggestion 直接相关文件/测试。
- `backend/app/modules/knowledge/metadata_suggestions.py`
- `backend/app/modules/knowledge/review_service.py`
- `backend/app/api/admin_reviews.py`
- `backend/tests/test_metadata_suggestions.py`
- `frontend/src/views/AdminReviewsView.vue`
- `frontend/src/api/adminPlatform.js`
- `frontend/tests/AdminReviewsView.test.js`
- `docs/technical-design.md` 与 Stage 24.5 metadata governance 边界相关段落。

不要进入 24.6，不读取历史 RAG 评估大型 JSON，不触碰受保护 auth 文件。

## 5. 唯一下一任务

**执行 Stage 24.5 follow-up 独立验收。**

只复核本 follow-up 的只读 GET、显式 generate、accept/reject 404、revision 并发、配置/source 白名单、事务 rollback、前端空态与迁移级联语义；通过后再由后续任务决定是否放行 24.6。
