# 当前开发交接

> 最后更新：2026-08-06
> 本文件只保留当前事实、工作区边界和一个下一任务。

## 1. 当前真实状态

Stage 24.5 元数据治理已完成本地开发与无模型验证，未部署、未推送，未调用真实模型、Embedding、OCR、视觉、SMTP、Docling 或生产网络/数据。

24.5 在 `knowledge` 模块内新增独立的元数据建议治理链路：

- 新增 `metadata_suggestions` 持久化表和 `MetadataSuggestionService`。建议与正式文档元数据分离，状态固定为 `suggested -> accepted / edited / rejected`，并使用 `status + revision` 原子迁移处理并发审核；重复或过期确认返回稳定冲突。
- 建议记录只保存结构化字段、受限证据片段/元素引用、逐字段置信度、解析 warning、suggestion source、创建/审核人和时间；不保存全文。证据、warning、confidence 和错误类型均做边界清洗。
- 新增 `MetadataSuggestionPort`，默认 `disabled`，测试可用 `fake`；本阶段没有真实模型实现、没有读取密钥、没有付费或网络调用。Port 失败会生成受限失败建议，不阻塞人工审核或发布。
- 管理员可在审核详情中原样接受、编辑后接受或拒绝建议。确认后才由 application service 写入正式 `document_versions` 字段并记录 audit；未确认建议不会污染 `document_versions`、Chroma chunk metadata 或 RAG filter。
- `document_versions` 新增正式字段 `disease_topics`、`document_type`、`published_year`，并复用既有 `department`、`source`、`review_due_at`。已确认建议若发生在发布前，会在审核发布事务创建 `DocumentVersion` 时应用；发布后确认则直接更新已有版本。
- 替换/回滚路径会保留新增正式元数据字段；演示账号清理维护命令已分类并清理 `metadata_suggestions.created_by/reviewed_by` 用户外键，避免安全预检误阻塞。
- 管理员审核 UI 在现有审核卡片内新增紧凑元数据治理区，展示建议值、管理员确认值、证据、置信度、warning、失败/冲突/loading/error 状态；没有重做整体视觉。

24.1-24.4 状态保持不变：24.1 解析契约、24.2a 本地 DOCX/Markdown/HTML、24.2b 受控网页快照、24.3 未晋级 Docling 候选、24.4 OCR/Vision Port+Fake+资产生命周期仍按各自默认关闭/无真实供应商边界运行。

开源借鉴记录：24.5 参考 Docling 的解析产物/provenance 与治理分离、RAGFlow 的文档处理状态可见性、Unstructured 的 Element/metadata 分离、Dify 的数据集治理状态、Haystack 的独立 metadata extractor 组件边界；没有复制第三方源码，没有新增依赖。

## 2. 本地验证结果

已通过：

```text
backend\.venv\Scripts\python.exe -m pytest -q backend\tests\test_metadata_suggestions.py backend\tests\test_admin_reviews_api.py backend\tests\test_migrations.py
31 passed, 128 warnings

D:\Nodejs\npm.cmd --prefix frontend test -- AdminReviewsView.test.js
1 file / 2 tests passed

D:\Nodejs\npm.cmd --prefix frontend test
19 files / 76 tests passed

backend\.venv\Scripts\python.exe -m pytest -q backend\tests\test_demo_account_maintenance.py
8 passed

backend\.venv\Scripts\python.exe -m pytest -q backend\tests
576 passed, 1 skipped, 131 warnings

D:\Nodejs\npm.cmd --prefix frontend run test:stream
SSE parser test passed

D:\Nodejs\npm.cmd --prefix frontend run build
Vite production build passed
assets: index-Dp6yTVJN.css / index-CtkNQ9bJ.js

backend\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini heads
0028_metadata_suggestions (head)

git diff --check
passed (only Git CRLF normalization warnings)

git diff --cached --check
passed

Protected auth hash
9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0
```

迁移往返已由完整 backend 中的 `backend/tests/test_migrations.py` 覆盖，包括 `0027 -> head -> 0027` 的 Stage 24.5 往返。

未执行项：未做生产健康/容器/迁移/静态资源/错误计数检查；本阶段不做生产操作。未调用真实模型、Embedding、OCR、视觉、SMTP、Docling、Reranker 或生产网络。

## 3. 工作区与安全边界

- 当前分支：`main`。
- 本任务只允许本地提交，不推送、不部署。
- `backend/app/modules/auth/service.py` 是受保护用户改动，禁止读取正文、修改、格式化、暂存、提交、回退或覆盖。目标 SHA-256 必须保持：
  `9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0`。
- 不读取 `.env`、真实上传资料、Chroma 数据、数据库备份或正文日志。

## 4. 新任务阅读范围

新窗口先完整阅读 `AGENTS.md` 和本文件。若执行唯一下一任务 24.6，只读：

- `docs/stage24-document-intelligence-and-stability-design.md` 的第 7、9、10、11 节。
- `docs/technical-design.md` 的 Stage 24.1-24.5 增补中与版本、去重、失效治理、metadata formal fields 直接相关段落。
- `docs/stage24-open-source-benchmark.md` 中 RAGFlow、Dify、Haystack、Unstructured 与知识治理/重复检测/版本状态相关条目。
- `knowledge` 的 `models`、`metadata_suggestions`、`review_service`、`asset_service`、`lifecycle`、`governance_service`、`repository`、submission/review API 与相关测试。
- 前端只在涉及管理员治理筛选或确认交互时读取 `AdminReviewsView.vue`、资产治理页面和对应 API/test。

不要读取历史 RAG 评估大型 JSON，不进入 24.7+，不触碰受保护 auth 文件。

## 5. 唯一下一任务

**执行 Stage 24.6 去重、版本和失效补强。**

在 24.5 已确认的正式元数据字段基础上，只补标准化正文哈希、近重复提示、版本沿袭与失效治理筛选。所有自动判断只做提示，不自动删除、不自动合并、不自动发布；真实 Embedding、模型、生产数据变更和部署仍需独立闸门。
