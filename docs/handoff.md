# 当前开发交接

> 最后更新：2026-08-06
> 本文只保留当前事实、工作区边界和一个下一任务。

## 1. 当前真实状态

Stage 24.7 `corpus_v2` 已完成本地实现和 coverage 口径 follow-up，等待独立验收；未进入 24.8，未部署、未推送，未调用真实 Qwen、Embedding、Reranker、OCR、Vision、SMTP、Docling、生产网络或任何收费供应商。

本阶段新增的是可复现、不可覆盖 `corpus_v1`、当前不导入生产的离线评估资产与工具：

- `backend/app/evaluation/corpus_v2.py` 定义 `corpus_v2` manifest、`eval_v2`、覆盖矩阵、清洗/重复报告和无费用 preflight 的 Pydantic 契约与构建函数。
- `backend/evaluation/corpora/corpus_v2_manifest.json` 记录 10 个待审 fixture placeholder，包含稳定 id、相对路径、来源/许可待审字段、科室、疾病主题、格式、语言、治理状态、parser 预期和表格/扫描页/图片标记。当前所有内容哈希均为 `unknown`，不得视为已下载真实资料。
- `backend/evaluation/corpora/corpus_v2_coverage_matrix.json` 覆盖基础事实、多来源、表格、扫描/OCR、图片/视觉、拒答、版本冲突、重复、多格式和网页快照，并严格区分 `planned_count` 与 `current_count`。当前 10 个 documents 均非 ready，8/9 eval cases 为 blocked；document-driven current 全为 0，只有 refusal 的非 blocked case 可计 current=1，10 个覆盖类别均仍有 gap。
- `backend/evaluation/corpora/corpus_v2_cleaning_dedup_report.json` 只基于 manifest metadata 生成，exact bytes、normalized text、near hint 分开记录，`auto_deleted=false`。
- `backend/evaluation/datasets/eval_v2.json` 绑定 `corpus_v2` checksum；缺少 fixture 或需要 OCR/Vision 的题保持 `blocked`，不伪造 golden answer。
- `backend/scripts/preflight_corpus_v2.py` 从 `backend` 目录执行 `.\.venv\Scripts\python.exe -m scripts.preflight_corpus_v2 --check`，校验 manifest/schema/checksum/引用/覆盖/预算。no-cost gate 由“当前 provider calls 全为 0 且不处于执行 provider 模式”派生，不再是常量 True。
- `backend/evaluation/corpora/corpus_v2_intake_template.md` 是后续人工导入清单模板；若现有 27 份资料要纳入 v2，必须另行人工确认来源、许可、文件哈希和使用边界，不能在本阶段读取真实正文或编造来源。

`docs/development-roadmap.md` 已将 24.6 hardening 标记为已完成并通过独立验收，将 24.7 标记为 follow-up 完成、待独立验收。`docs/technical-design.md`、`docs/stage24-open-source-benchmark.md` 和 `backend/evaluation/README.md` 已记录 v2 边界、planned/current 覆盖口径、无费用闸门和开源参考思想；没有复制第三方源码，也没有新增依赖。

## 2. 本地验证结果

本轮 Stage 24.7 已通过：

```text
backend\.venv\Scripts\python.exe -m pytest -q backend\tests\test_corpus_v2.py backend\tests\test_evaluation_assets.py backend\tests\test_evaluation_dataset.py
23 passed

backend\.venv\Scripts\python.exe -m py_compile backend\app\evaluation\corpus_v2.py backend\scripts\preflight_corpus_v2.py backend\tests\test_corpus_v2.py
passed

cd backend
.\.venv\Scripts\python.exe -m scripts.preflight_corpus_v2 --check
corpus_v2 OK: documents=10; cases=9; coverage_gaps=10; dedup_unknown=10; provider_calls=0

backend\.venv\Scripts\python.exe -m pytest -q backend\tests
605 passed, 1 skipped, 140 warnings

git diff --check
passed（仅 CRLF 提示）

git diff --cached --check
passed

Protected auth hash
9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0
```

前端未改动，本阶段未运行完整前端、SSE 或 build；本任务只新增后端 evaluation 静态资产、脚本、测试和文档。未运行 Alembic 往返，因为没有数据库迁移。

## 3. 工作区与安全边界

- 当前分支：`main`。
- 本任务只允许本地提交；禁止 push、部署、生产操作、生产网络抓取、真实模型或收费调用。
- `backend/app/modules/auth/service.py` 是受保护用户改动，禁止读取正文、修改、格式化、暂存、提交、回退或覆盖；只允许 SHA-256 校验，目标值必须保持：
  `9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0`。
- 不读取 `.env`、真实上传资料、Chroma 数据、数据库备份、历史大型 reports JSON 或正文日志。

## 4. 新任务阅读范围

新窗口先完整阅读 `AGENTS.md` 和本文。若执行唯一下一任务，只读：

- `docs/stage24-document-intelligence-and-stability-design.md` 中 `corpus_v2`、安全和验收相关段落。
- `docs/technical-design.md` 的 Stage 24.7 Corpus V2 Evaluation Asset Boundary。
- `docs/stage24-open-source-benchmark.md` 的 Stage 24.7 adopted references。
- `backend/app/evaluation/corpus_v2.py`、`backend/scripts/preflight_corpus_v2.py`、`backend/evaluation/corpora/corpus_v2_manifest.json`、`backend/evaluation/datasets/eval_v2.json`、`backend/tests/test_corpus_v2.py` 及直接相关 v1 静态资产测试。

禁止读取历史大型 reports JSON，禁止触碰受保护 auth 文件正文。

## 5. 唯一下一任务

**执行 Stage 24.7 独立验收。**

只复核 `corpus_v2` manifest/schema/checksum、覆盖矩阵、清洗/重复报告、`eval_v2` 引用、blocked/provider-dependent 语义、no-cost preflight、不可覆盖 `corpus_v1`、不读取真实资料和零真实 provider calls。验收通过后，后续任务再决定是否进入 24.8。
