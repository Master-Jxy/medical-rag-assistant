# 当前开发交接

> 最后更新：2026-08-06
> 本文件只保留当前事实、工作区边界和一个下一任务。

## 1. 当前真实状态

Stage 24.4 已完成本地开发与无模型验证，未部署、未推送，未调用真实 OCR、视觉供应商、Qwen、Embedding、Reranker、SMTP、Docling 或生产网络。

24.4 在 `knowledge` 模块内新增 OCR/视觉文档理解基础设施：

- 应用层定义 `OcrPort`、`VisionDocumentPort`、结构化 request/result/error contract 与 `DocumentEnrichmentService`。
- infrastructure 只提供 `DisabledOcrAdapter`、`DisabledVisionDocumentAdapter` 和 Fake adapter；没有真实供应商实现，没有读取密钥，没有网络调用。
- `EnrichmentResourcePolicy` 集中约束默认关闭、显式批准、页数、图片数、单图/总字节、单图/总像素、单文档调用次数、单次超时、并发和自动重试 0。若未启用或未批准，只写入等待/跳过/受限状态，不执行供应商调用。
- 疑似 CT、X 光、病理、放射等诊断影像会确定性标记 `restricted`，不做自动解读；24.4 范围只覆盖扫描 PDF 页、检查报告截图、药盒文字、表格截图、流程图和医学资料插图的文档理解基础设施。
- 新增 `ControlledDocumentAssetStore`，图片资产文件只使用服务端生成 UUID 文件名保存在 `document_asset_dir` 下；parser/模型返回的路径不被信任。撤回、拒绝、发布隔离清理、公共文档删除和替换旧文档清理均有资产目录清理钩子。
- 新增 PNG/JPEG 本地报告截图上传支持。`FileTypePolicy` 通过魔数、Pillow 结构校验、10 MB 基线和像素上限校验图片；客户端 MIME 不能绕过服务端校验。图片资料默认只进入 `pending_review` 并标记 `waiting_enrichment`，不会生成假正文，也不能在管理员确认前发布空文本。
- `ParsedPreview` 兼容层保留原有 PDF/TXT/DOCX/Markdown/HTML 行为，同时将图片资产摘要和 enrichment 状态投射到现有 `parse_quality` JSON；未新增 API 响应字段、数据库字段或迁移。
- 前端普通上传和管理员新增/替换 accept 已同步包含 `.png,.jpg,.jpeg`，页面布局未重做。

24.1-24.3 状态保持不变：24.1 已建立 `ParseRequest`、`ParsedDocument`、`ParsedElement`、`ParsedAsset`、`ParseQuality`、`DocumentParserPort` 和 `ParserRegistry`；24.2a 已支持 DOCX/Markdown/HTML 本地文件；24.2b 已支持默认关闭且 allowlist 约束的受控网页快照；24.3 已建立默认关闭、未晋级的 Docling 复杂 PDF 候选离线闸门，生产继续使用 PyPDF 基线。

开源借鉴记录：24.4 参考 Docling picture/page provenance、Unstructured hi_res/OCR strategy、Dify file/image upload quota 和 RAGFlow parser task 状态的边界思想；没有复制第三方源码，没有引入 Docling/MinerU/Unstructured 重型栈。

24.4 follow-up security/accounting patch (2026-08-06):
- `ControlledDocumentAssetStore` now materializes only direct PNG/JPEG upload
  assets marked `source_kind=uploaded_image_file` after revalidating source
  magic bytes, Pillow MIME, dimensions, byte size, pixel count, and SHA-256.
  PDF/Docling discovered image assets remain provenance-only with
  `materialized=false` and `asset_not_materialized`; they are not copied from
  the source PDF, do not receive fake image suffixes, and are not sent to
  OCR/Vision ports.
- Asset cleanup IDs are now limited to the project identifier alphabet and
  explicitly reject `.`, `..`, blank, whitespace-wrapped, control-character,
  path-separator, and drive-like values before recursive cleanup. Boundary
  checks under `document_asset_dir` remain in place, and recursive cleanup
  failures raise `DocumentStoreError` instead of being silently swallowed.
- Enrichment call limits now count concrete port operations. One materialized
  image plans one OCR call and one vision call; the service refuses over-limit
  plans before any port call. OCR/Vision `ModelUsage` is aggregated and settled
  through the existing quota gate; failures before any usage release the
  reservation, while partial failures settle usage already spent.
- Diagnostic image restriction now uses explicit image type/purpose categories
  and filename tokens, so ordinary names such as `fact-sheet.png` and
  `document.png` are not rejected merely because a word contains `ct`.
- Publication isolation cleanup records the existing
  `knowledge_submission.cleanup_pending` audit warning for both `OSError` and
  `DocumentStoreError`. No real OCR, vision provider, model, network, production
  data, deployment, or protected auth change was performed.

24.4 final transaction follow-up (2026-08-06):
- Document and submission asset cleanup now has explicit
  stage/restore/finalize/cleanup-pending semantics. `stage_*_assets_for_delete`
  atomically renames controlled asset directories to `.trash` before the
  business commit; pre-commit failures restore the tombstone, while post-commit
  finalization failures no longer enter rollback paths.
- Post-commit asset cleanup failures write durable `.cleanup_pending/*.json`
  markers containing only scope, object id, tombstone relative path, and error
  type. `retry_pending_cleanups()` removes tombstones and clears markers when
  cleanup can later succeed.
- Public delete, managed permanent delete, replace, ordinary withdraw, reject,
  and publication isolation cleanup now use the staged protocol at their
  transaction boundaries. Admin review paths still record
  `knowledge_submission.cleanup_pending` audit warnings; no broad job queue
  refactor or production operation was performed.

24.4 final security follow-up (2026-08-06):
- `retry_pending_cleanups()` now validates cleanup markers before deleting any
  tombstone: scope must be `submission` or `document`, `object_id` must pass the
  safe-id policy, marker filename/payload/tombstone deletion id must match, and
  tombstones must resolve directly under `.trash/{scope}s` with basename
  `.{object_id}.{32hex}.deleting`. Malicious markers that point at normal
  `documents/` or `submissions/` directories, cross scopes, use traversal,
  wrong basenames, mismatched filenames, or symlinks are skipped and retained.
- Post-commit marker writes are now best-effort. If tombstone deletion fails and
  `.cleanup_pending` marker write/rename also fails, delete/replace/withdraw/
  reject still return the already committed business success; lifecycle and
  submission services log a non-sensitive warning, and review paths still try to
  record `knowledge_submission.cleanup_pending`.

## 2. 本地验证结果

已通过：

```text
backend\.venv\Scripts\python.exe -m pytest -q backend/tests/test_document_enrichment.py backend/tests/test_document_service.py backend/tests/test_knowledge_submissions_api.py backend/tests/test_admin_reviews_api.py
75 passed, 1 skipped, 2 warnings

backend\.venv\Scripts\python.exe -m pytest -q backend/tests/test_document_enrichment.py backend/tests/test_document_service.py backend/tests/test_knowledge_submissions_api.py backend/tests/test_admin_reviews_api.py
66 passed, 2 warnings

backend\.venv\Scripts\python.exe -m pytest -q backend/tests/test_document_parser_contract.py backend/tests/test_document_enrichment.py backend/tests/test_knowledge_submissions_api.py backend/tests/test_admin_reviews_api.py backend/tests/test_document_service.py
52 passed, 2 warnings

backend\.venv\Scripts\python.exe -m pytest -q backend/tests
570 passed, 1 skipped, 120 warnings

backend\.venv\Scripts\python.exe -m pytest -q backend/tests/test_document_enrichment.py
32 passed

backend\.venv\Scripts\python.exe -m pytest -q backend/tests/test_document_enrichment.py backend/tests/test_document_parser_contract.py backend/tests/test_knowledge_submissions_api.py backend/tests/test_admin_reviews_api.py backend/tests/test_document_service.py
73 passed, 2 warnings

D:\Nodejs\npm.cmd --prefix frontend test
18 files / 74 tests passed

D:\Nodejs\npm.cmd --prefix frontend run test:stream
SSE parser test passed

D:\Nodejs\npm.cmd --prefix frontend run build
Vite production build passed
assets: index-Bgk7zuj3.css / index-CYNSg3p8.js

backend\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini heads
0027_web_snapshot_submissions (head)

git diff --check
passed

git diff --cached --check
passed

Protected auth hash
9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0
```

本阶段没有新增 Alembic 迁移；完整 backend 已覆盖迁移测试，Alembic head 保持 `0027_web_snapshot_submissions`。

未执行项：没有生产健康/容器/迁移/静态资源/日志检查；本阶段不做生产操作。

## 3. 工作区与安全边界

- 当前分支：`main`。
- 本任务只允许创建本地提交，不推送、不部署。
- `backend/app/modules/auth/service.py` 是受保护用户改动，禁止读取正文、修改、格式化、暂存、提交、回退或覆盖。当前目标 SHA-256 必须保持：
  `9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0`。
- 不读取 `.env`、真实上传资料、Chroma 数据、数据库备份或正文日志。
- Stage 24.4 没有真实供应商、真实模型下载、付费调用、生产配置或生产数据依赖。

## 4. 新任务阅读范围

新窗口先完整阅读 `AGENTS.md` 和本文件。若执行唯一下一任务 24.5，只读：

- `docs/stage24-document-intelligence-and-stability-design.md` 的 1、2、3、4、6、9、10、11 节。
- `docs/technical-design.md` 的 Stage 24 增补中 24.1-24.4 相关段落。
- `docs/stage24-open-source-benchmark.md` 中 Docling、Unstructured、Dify、RAGFlow、Haystack 对应条目。
- `knowledge` 的 ingestion contracts、parser、enrichment、asset storage、submission/review/lifecycle、governance/version 相关代码与测试。
- usage/quota 只在元数据建议需要预算或账本边界时定向读取。

不要读取历史 RAG 评估大型 JSON，不进入 24.6+。

## 5. 唯一下一任务

**执行 Stage 24.5 元数据建议与管理员确认。**

在 24.1-24.4 的结构化解析、网页快照、复杂 PDF 候选、OCR/视觉 Port 与资产生命周期基础上，只实现元数据建议状态机、管理员确认/编辑、审核 UI 和审计。AI/模型建议必须默认关闭或 Fake；不得调用真实模型、Embedding、OCR、视觉、生产数据或付费供应商。受保护 auth 文件继续保持上述哈希和边界。
