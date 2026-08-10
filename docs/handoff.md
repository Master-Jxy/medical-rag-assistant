# 当前开发交接

> 最后更新：2026-08-10
> 本文只保留当前事实、工作区边界和一个下一任务。

## 1. 当前真实状态

Stage 24.8 完整验收与发布候选已完成本地验证，并已推送和部署到服务器提交 `39a56ab6f8d6ad8179ce1be4449f5d5e112c44c8`。生产备份成功，数据库迁移到 `0029_dedup_version_governance`，HTTP/HTTPS、健康接口和四个容器均已验收通过。未调用真实 Qwen、Embedding、Reranker、OCR、Vision、SMTP、Docling、生产抓取或任何收费供应商。

Stage 25 多模态聊天与输入器升级已完成 25.1～25.8 的全部本地开发和发布候选验收。新增 `0030_multimodal_chat_assets`、私有图片资产与授权预览、聊天专用结构化视觉边界、RAG/Agent图片消息、受控Agent观察工具、共享附件草稿和输入器/侧栏修复。完整实现边界见 `docs/stage25-multimodal-chat-design.md`、`docs/technical-design.md` 的 Stage 25 章节和 `docs/release-audit-stage25-multimodal-chat.md`。

总控窗口已使用一张非医疗 UI 截图完成真实 DashScope 最小视觉验收。旧设计别名
`qwen-vl-max-latest` 对当前 API Key 返回 `403 AccessDenied`；模型目录预检确认
`qwen3-vl-plus` 可用，随后真实调用成功返回可由 `VisionObservation` 校验的结构化结果，
且没有输出密钥、图片正文或完整提示词。默认视觉模型已修正为 `qwen3-vl-plus`。
当前仍未 push、连接生产、备份、部署或修改服务器。

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

Stage 25 本地发布候选已通过：

```text
backend\.venv\Scripts\python.exe -m pytest -q backend\tests
618 passed, 1 skipped, 140 warnings

D:\Nodejs\npm.cmd --prefix frontend test
20 files / 82 tests passed

D:\Nodejs\npm.cmd --prefix frontend run test:stream
SSE parser test passed

D:\Nodejs\npm.cmd --prefix frontend run build
Vite production build passed
assets: index-Xv-mGLQX.css / index-CPEwi2bu.js

Stage 25 focused matrix
media + vision + RAG images + Agent images + deletion/recovery: 25 passed

Alembic 临时 SQLite roundtrip
0029 -> 0030 -> 0029 -> 0030 passed；三张Stage25表随升级/降级正确出现和移除

Python compile/import smoke
compileall passed：Stage25触及模块、0030迁移和维护命令，auth service excluded
import smoke passed：media、vision、Agent thread、RAG conversation、demo maintenance 6个关键模块

Frontend browser acceptance (Playwright CLI, local Vite, mocked no-cost API)
1440x900 / 1280x800 / 1024x768 / 390x844 layout passed
RAG and Agent image selection/preview/removal and pure-image send enablement passed
desktop sidebar 220px/76px and mobile drawer passed; console errors=0
真实后端提交、上传失败重试和视觉结果由Fake自动化测试覆盖，未伪造为浏览器端到端生产验收

Impeccable detector
Only existing global Inter font warning; no Stage25 layout blocker

Security checks
tracked credential literal scan passed；未提交backend/data/media运行数据
临时迁移库已删除；浏览器和Vite进程已关闭

git diff --check
passed（仅 CRLF 提示）

git diff --cached --check
passed

Protected auth hash
9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0
```

SKIP 项：

- 真实DashScope视觉最小调用：PASS；`qwen3-vl-plus` 返回结构化观察，供应商请求ID存在。
- push、服务器备份、`0029 -> 0030`生产迁移、容器重建、生产健康和回滚验收：本窗口明确禁止，全部留给总控。
- 生产测试账号清理：仍需独立授权；本次只更新维护命令对Stage25私有媒体的安全边界。

本地Stage25提交依次为：`a7a15f2`、`c894329`、`9a128cd`、`6fbe243`、`d6d86b9`、`265f111`、`364ecd2`；文档提交以当前Git记录为准。均未push。

## 3. 工作区与安全边界

- 当前分支：`main`。
- Stage 25 仅完成本地发布候选；当前生产仍停留在Stage 24提交 `39a56ab` 和迁移 `0029`。
- `backend/app/modules/auth/service.py` 是受保护用户改动，禁止修改、格式化、暂存、提交、回退或覆盖；提交前后只允许 SHA-256 校验，目标值必须保持：
  `9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0`。
- 不读取 `.env`、真实上传资料、Chroma 数据、数据库备份、历史大型 reports JSON 或正文日志。

## 4. 新任务阅读范围

总控发布窗口先完整阅读 `AGENTS.md` 和本文，再定向读取：

- `docs/release-audit-stage25-multimodal-chat.md`
- `docs/stage25-multimodal-chat-design.md` 的真实调用与发布闸门
- `docs/deployment.md` 和实际使用的部署/备份脚本
- `backend/alembic/versions/0030_multimodal_chat_assets.py`
- 真实视觉配置工厂、DashScope适配器和最小验收测试

禁止读取真实 `.env`、生产正文日志、真实上传文件、Chroma 数据或受保护 auth 文件正文。

## 5. 唯一下一任务

**由总控推送 Stage 25，完成生产备份、0030迁移、容器重建和线上验收**

总控仍必须保护 `backend/app/modules/auth/service.py`，并在发布中保持生产数据卷、HTTPS overlay、备份和回滚边界。
