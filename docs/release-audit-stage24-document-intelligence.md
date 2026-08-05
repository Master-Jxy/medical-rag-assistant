# Stage 24 文档智能与稳定性发布候选审计

> 审计日期：2026-08-06
> 审计范围：Stage 24.0 到 24.8 本地发布候选；不部署、不推送、不连接生产。
> 当前结论：发布候选本地验收通过，等待用户单独授权部署。

## 1. 发布范围

- Stage 24.0：RAG/Agent 跨页面流式继续、后台未读、陈旧 pending 恢复、停止/退出/401 清理和日志控制台复核。
- Stage 24.1：知识模块结构化解析契约、`DocumentParserPort`、`ParserRegistry` 与 PDF/TXT 兼容层。
- Stage 24.2：DOCX/Markdown/HTML 本地文件支持、统一 `FileTypePolicy`、HTML 原文不可执行预览、受控网页快照导入和 SSRF 防护。
- Stage 24.3：默认关闭的 Docling 复杂 PDF 候选、子进程硬超时、离线闸门、PyPDF 回退和未晋级语义。
- Stage 24.4：OCR/Vision Port、Disabled/Fake adapter、资源/费用闸门、图片资产生命周期和清理补偿 hardening。
- Stage 24.5：元数据建议治理、显式管理员生成/确认、Fake/Disabled suggestion port、并发状态迁移和中文审核 UI 修复。
- Stage 24.6：exact/normalized/near 重复信号、版本沿袭、失效治理、RAG/Agent 检索 eligibility 和扫描上限 hardening。
- Stage 24.7：`corpus_v2` manifest、coverage matrix、cleaning/dedup report、`eval_v2` 和 no-cost preflight；readiness accounting follow-up 已把 planned/current 覆盖分开。
- Stage 24.8：本地完整验收、发布/回滚预检和本审计文件。

明确不在本候选中启用：真实 Docling、OCR、Vision、Qwen、Embedding、Reranker、SMTP、生产网页抓取、生产导入、部署或任何收费调用。

## 2. 验证矩阵

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| 完整后端 | PASS | `backend\.venv\Scripts\python.exe -m pytest -q backend\tests` -> `605 passed, 1 skipped, 140 warnings` |
| 完整前端 | PASS | `D:\Nodejs\npm.cmd --prefix frontend test` -> `19 files / 79 tests passed` |
| SSE contract | PASS | `D:\Nodejs\npm.cmd --prefix frontend run test:stream` -> `SSE parser test passed` |
| 前端正式构建 | PASS | `D:\Nodejs\npm.cmd --prefix frontend run build` -> Vite build passed，默认同源包 `index-CGLlwHMM.js` |
| Python compile smoke | PASS | 编译 `backend/app` 与 `backend/scripts` 共 249 个 Python 文件，排除受保护 `auth/service.py` |
| Import smoke | PASS | `app.main`、`app.evaluation.corpus_v2`、`scripts.preflight_corpus_v2` 导入成功 |
| Alembic head | PASS | `0029_dedup_version_governance (head)` |
| Alembic 往返 | PASS | 临时 SQLite `upgrade head -> downgrade 0028_metadata_suggestions -> upgrade head` 通过 |
| Stage24 focused matrix | PASS | 16 个相关测试文件，`167 passed, 1 skipped, 2 warnings` |
| 安全 focused matrix | PASS | upload/SSRF/auth/permissions/retrieval eligibility，`37 passed, 2 warnings` |
| corpus_v2 preflight | PASS | `documents=10; cases=9; coverage_gaps=10; dedup_unknown=10; provider_calls=0` |
| Git 跟踪运行数据检查 | PASS | `git ls-files` 未命中 `.env`、上传目录、Chroma、备份、本地 review、dist、node_modules、SQLite/DB 文件 |
| 高风险密钥模式扫描 | PASS | tracked files 文件名扫描未命中 DashScope/AKIA/private key 等高风险模式；不输出秘密值 |
| `.gitignore` | PASS | 忽略 `.env`、`deploy/.env`、`frontend/dist`、`node_modules`、上传、Chroma、备份和本地正文 review |
| Compose/Dockerfile/Nginx 静态检查 | PASS | YAML 可解析；Compose 含 mysql/redis/backend/web；Dockerfile 有 FROM/COPY；Nginx 含 11m 上传限制、SSE buffering off、nosniff、SAMEORIGIN |
| Docker/Compose CLI 语法 | SKIP | 本机无 `docker` 命令，不安装 |
| Nginx `-t` | SKIP | 本机无 `nginx` 命令，不安装 |
| 本地服务健康 smoke | PASS | 临时 SQLite 后端 `http://127.0.0.1:8018/api/v1/health` 返回 200；临时静态前端 `http://127.0.0.1:5178/` 返回 200；已停止进程并清理临时库 |
| 本地浏览器点击/控制台验收 | SKIP | 项目没有可用 Playwright 依赖；`npm exec` 会临时下载 Playwright，因禁止网络下载/新增依赖而停止。未伪造截图或控制台结果 |

## 3. Stage24 Focused Matrix

执行命令：

```powershell
backend\.venv\Scripts\python.exe -m pytest -q `
  backend\tests\test_conversation_recovery.py `
  backend\tests\test_conversation_stream_chat.py `
  backend\tests\test_agent_conversation_api.py `
  backend\tests\test_document_parser_contract.py `
  backend\tests\test_upload_protection.py `
  backend\tests\test_knowledge_submissions_api.py `
  backend\tests\test_admin_reviews_api.py `
  backend\tests\test_web_snapshot_fetcher.py `
  backend\tests\test_parser_experiments.py `
  backend\tests\test_document_enrichment.py `
  backend\tests\test_metadata_suggestions.py `
  backend\tests\test_stage24_deduplication_policy.py `
  backend\tests\test_admin_knowledge_assets_api.py `
  backend\tests\test_rag_ports.py `
  backend\tests\test_agent_knowledge_tools.py `
  backend\tests\test_corpus_v2.py
```

覆盖关系：

- 稳定恢复：`test_conversation_recovery.py`、`test_conversation_stream_chat.py`、`test_agent_conversation_api.py`
- Parser contract 与多格式提交/审核：`test_document_parser_contract.py`、`test_upload_protection.py`、`test_knowledge_submissions_api.py`、`test_admin_reviews_api.py`
- Web snapshot SSRF：`test_web_snapshot_fetcher.py`
- Docling fallback：`test_parser_experiments.py`
- OCR/Vision Disabled/Fake 与资产生命周期：`test_document_enrichment.py`
- Metadata governance：`test_metadata_suggestions.py`、`test_admin_reviews_api.py`
- Dedup/version/expiry：`test_stage24_deduplication_policy.py`、`test_admin_knowledge_assets_api.py`
- RAG/Agent expired filtering：`test_rag_ports.py`、`test_agent_knowledge_tools.py`
- corpus_v2 preflight/readiness accounting：`test_corpus_v2.py`

结果：`167 passed, 1 skipped, 2 warnings`。

## 4. 安全与边界

- 受保护文件 `backend/app/modules/auth/service.py` 未暂存、未提交；最终 SHA-256 必须保持 `9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0`。
- 本审计未读取 `.env`、真实上传资料、Chroma 数据、数据库备份、历史大型 reports JSON 或正文日志。
- CORS、上传限制、路径穿越、SSRF、权限和 retrieval eligibility 由 focused tests 与静态配置检查覆盖。
- 本地临时 smoke 使用系统 Temp 下 SQLite 与运行目录，结束后停止进程并删除临时库；未创建生产数据。

## 5. 已知限制

- Docling 仍是可选候选，默认关闭，未安装、未真实运行、未晋级；生产继续使用 PyPDF 基线。
- OCR/Vision 仍是 Port + Disabled/Fake + 资源/费用闸门；未调用真实供应商。
- 元数据建议真实模型默认关闭；Stage 24.5 只使用 Disabled/Fake/manual 语义。
- `corpus_v2` 当前是 10 个规划 placeholder，0 ready，10 个 coverage gaps；它是待收集蓝图，不是已完成真实语料扩充。
- 受控网页快照能力不做生产抓取；生产抓取默认关闭并需要独立 allowlist/授权。
- 本地浏览器点击与控制台错误检查因可用工具限制跳过；部署前若用户要求，可在具备浏览器自动化依赖的环境补跑。
- 本候选未生产导入、未网络抓取、未真实模型调用、未推送、未部署；服务器部署仍需用户单独授权。

## 6. 发布与回滚预检

部署前必须先由用户单独授权，然后按 `docs/deployment.md` 执行：

1. 本地确认发布提交 SHA 与上一可回滚提交 SHA。
2. 服务器工作区必须干净，只能拉取指定提交；禁止直接编辑服务器源码。
3. 发布前运行 `deploy/backup.sh`，备份 MySQL、`app_data`、`chroma_data`、Redis、`deploy/.env`、Compose 和清单，并校验 `SHA256SUMS`。
4. 先执行 Alembic 迁移，再重建受影响服务；不得使用 `docker compose down -v`。
5. 重建后检查四容器健康、`/api/v1/health`、HTTP/HTTPS、静态资源、未授权 401 和核心业务无费用黑盒。
6. 任一关键失败即停止；代码回滚到上一提交，必要时使用已校验备份恢复数据卷。

当前本地发布候选未执行上述生产步骤。
