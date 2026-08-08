# 当前开发交接

> 最后更新：2026-08-09
> 本文只保留当前事实、工作区边界和一个下一任务。

## 1. 当前真实状态

Stage 24.8 完整验收与发布候选已完成本地验证，并已推送和部署到服务器提交 `39a56ab6f8d6ad8179ce1be4449f5d5e112c44c8`。生产备份成功，数据库迁移到 `0029_dedup_version_governance`，HTTP/HTTPS、健康接口和四个容器均已验收通过。未调用真实 Qwen、Embedding、Reranker、OCR、Vision、SMTP、Docling、生产抓取或任何收费供应商。

Stage 24 当前候选边界：

- 24.0 到 24.6 的稳定性、解析、多格式、网页快照、Docling fallback、OCR/Vision Fake/Disabled、元数据治理、去重/版本/失效和 RAG/Agent retrieval eligibility 已由完整后端和 focused matrix 覆盖。
- 24.7 `corpus_v2` 是离线评估蓝图，不是生产语料扩充：10 个 placeholder documents、0 ready、10 个 coverage gaps；`planned_count` 与 `current_count` 已分离，gap 只按可执行 current 计算。
- Docling/OCR/Vision/metadata model 仍默认关闭或 Disabled/Fake；真实供应商、真实抓取、真实导入和生产向量化必须另行授权。
- 新审计文件：`docs/release-audit-stage24-document-intelligence.md`。它记录 PASS/SKIP、证据命令、已知限制、备份和回滚预检。

`docs/development-roadmap.md` 已将 24.7 标记为已完成并通过独立验收，将 24.8 标记为已部署。`docs/technical-design.md` 已新增 Stage 24.8 release candidate validation boundary。

线上发布记录：

- GitHub `main` 已推送至 `39a56ab`。
- 服务器：`112.124.9.120`，工作区提交为 `39a56ab`，工作区干净。
- 备份：`/home/deploy/medical-rag-backups/backup-20260808T174209Z`。
- 迁移：`0029_dedup_version_governance (head)`。
- 容器：backend、web、mysql、redis 均为 healthy。
- HTTP 80 返回 308 跳转；HTTPS 首页和 `/api/v1/health` 返回成功。

## 2. 本地验证结果

Stage 24.8 已通过：

```text
backend\.venv\Scripts\python.exe -m pytest -q backend\tests
605 passed, 1 skipped, 140 warnings

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

Python compile/import smoke
py_compile OK: 249 files, auth service excluded
import smoke OK: app.main, app.evaluation.corpus_v2, scripts.preflight_corpus_v2

Stage24 focused matrix
167 passed, 1 skipped, 2 warnings

Security focused matrix
37 passed, 2 warnings

cd backend
.\.venv\Scripts\python.exe -m scripts.preflight_corpus_v2 --check
corpus_v2 OK: documents=10; cases=9; coverage_gaps=10; dedup_unknown=10; provider_calls=0

Static deploy config
compose yaml parsed, Dockerfiles/Nginx key directives present

Tracked runtime data scan
No tracked .env/upload/Chroma/backup/local_reviews/dist/node_modules/SQLite DB paths matched

High-risk secret filename scan
No tracked file matched DashScope/AKIA/private-key high-risk patterns

Local service health smoke
temporary SQLite backend health 200; temporary static frontend index 200; processes stopped and temp DB removed

git diff --check
passed（仅 CRLF 提示）

git diff --cached --check
passed

Protected auth hash
9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0
```

SKIP 项：

- Docker/Compose CLI 语法：本机没有 `docker` 命令，不安装。
- Nginx `-t`：本机没有 `nginx` 命令，不安装。
- 本地浏览器点击/控制台验收：项目没有可用 Playwright/browser 自动化依赖；`npm exec` 会触发临时下载，因本阶段禁止网络下载/新增依赖而停止，没有伪造截图或控制台结果。

提交前最终检查已记录。

## 3. 工作区与安全边界

- 当前分支：`main`。
- 本次 Stage 24 已完成推送和部署；后续任务仍禁止直接修改生产源码，必须先本地验证、备份，再按提交部署。
- `backend/app/modules/auth/service.py` 是受保护用户改动，禁止修改、格式化、暂存、提交、回退或覆盖；提交前后只允许 SHA-256 校验，目标值必须保持：
  `9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0`。
- 不读取 `.env`、真实上传资料、Chroma 数据、数据库备份、历史大型 reports JSON 或正文日志。

## 4. 新任务阅读范围

新窗口先完整阅读 `AGENTS.md` 和本文。若执行唯一下一任务，只读：

- `docs/deployment.md`
- `docs/release-audit-stage24-document-intelligence.md`
- `docs/stage24-document-intelligence-and-stability-design.md` 的 24.8、安全和验收段落
- `docs/technical-design.md` 的 Stage 24.8 Release Candidate Validation Boundary
- 必要时读取 deploy 脚本、Compose/Nginx 配置和当前提交元数据

禁止读取真实 `.env`、生产正文日志、真实上传文件、Chroma 数据或受保护 auth 文件正文。

## 5. 唯一下一任务

**观察 Stage 24 线上运行状态，收集真实错误和用户体验问题；不要立即启用 Docling、OCR、Vision 或导入 `corpus_v2` 真实资料。**

下一次发布前必须再次确认目标提交、服务器当前提交、备份目录、迁移顺序、回滚点和无真实供应商调用边界。
