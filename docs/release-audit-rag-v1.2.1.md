# RAG v1.2.1 本地发布审计

> 审计日期：2026-07-21
>
> 当前分支：`main`
>
> 审计基准提交：`82d1cb94bc3a11bb06ceb833cfbda747d7d1dd52`
>
> 审计完成时状态：本地发布候选验证通过，尚未暂存、提交、推送或更新服务器。后续Git发布结果以`docs/handoff.md`和GitHub记录为准。

## 1. 发布决定

任务7.1～7.7形成同一个阶段七发布候选。任务7.7有效检索排序没有候选达到预登记晋级门槛，因此本次发布继续使用冻结向量基线：

```text
RAG_HYBRID_SEARCH_ENABLED=false
RAG_RERANK_ENABLED=false
```

候选池、多样性、混合检索和Reranker仅作为默认关闭、可复现的实验能力发布，不接入当前`RagService`生产主链路。没有运行后续Qwen完整回答评估，也没有修改`eval_v1`黄金标准。

## 2. 候选发布范围

审计开始时工作区包含12个已跟踪修改文件和91个未跟踪文件，共103个阶段变更文件；本审计文件是随后新增的第104个候选文件。没有已暂存内容。

应纳入后续提交的范围：

- RAG Port、当前适配器、检索策略、关键词检索、RRF融合、候选选择和Rerank基础设施。
- 默认关闭的配置项、Chroma只读评估能力以及新上传片段的可核验元数据。
- `app/evaluation/`中的版本化语料、评估Runner、预算、预检、评分、人工复核和排序实验代码。
- `backend/evaluation/`中的`corpus_v1`、`eval_v1`、JSON Schema、无正文报告、计划和审查摘要。
- 评估、RAG Port、混合检索、Reranker、候选池和真实工厂装配的测试。
- 运行与校验脚本、`.env.example`、`.gitignore`、部署说明、路线图、技术设计和handoff。
- 首次真实排序的无效报告及失效说明：它们是明确命名的审计证据，不得与有效报告混淆。

## 3. 明确排除范围

以下路径已经通过`git check-ignore`确认不会进入候选提交：

- `backend/.env`、`deploy/.env`：真实密钥与连接信息。
- `backend/chroma_db/`：本地Chroma生产数据。
- `backend/data/uploads/`、`backend/data/`：上传文件和运行时数据。
- `backend/backups/`：数据库或数据备份。
- `backend/evaluation/local_reviews/`：包含回答正文的本地人工复核包。
- `frontend/node_modules/`、`frontend/dist/`：依赖与本机构建产物。
- `.venv/`、`__pycache__/`、`.pytest_cache/`、日志和IDE配置。

本地人工复核包`human_review_capture_v1.json`仍在忽略目录内，40题绑定校验通过，到期时间为2026-07-25；到期后必须删除，不能移动到版本化目录。

## 4. 敏感信息与正文检查

- 对全部已跟踪修改和未跟踪候选文件扫描常见DashScope Key、阿里云AccessKey和私钥格式，没有发现强敏感模式。
- `.env.example`只包含`your_dashscope_api_key_here`、`change_me`和随机密钥替换说明等占位符。
- 全部版本化评估报告未出现`question`、`answer_text`、`content`、`page_content`、`body`或`prompt`正文字段。
- 报告只保存题号、类别、文档ID、指标、阶段状态和脱敏Token/费用计量。
- 候选文件最大约235KB，没有意外大型二进制、数据库、向量库或压缩备份。

## 5. 冻结与发布报告哈希

| 产物 | SHA-256 |
| --- | --- |
| `current_baseline_v1.json` | `598952a8772fde26eac428cdad0335f889241f61d12b9c55bfabed5329a26ed5` |
| `human_review_capture_v1.json` | `db4a9afc6ed4404a17512dcf5ac39017bf3fb64cf6b8da06dc874c416b6f0a84` |
| `rag_v1_2_real_comparison_v1.json` | `f54e86a1b39518d998e861c101b225b160188d373488bca4fa821913c09e2893` |
| `retrieval_ranking_mock_v1.json` | `2ca18667421937937247ebd40d502fda9d07e884a026e1795017d86e9d12f773` |
| `retrieval_ranking_real_v1.json` | `d4bdb8ad0953463c215cfa02ee08125bde4f7bc8f0ecba68eb5b036684dbd365` |
| `retrieval_ranking_real_v1_invalid_vector_port_20260721.json` | `e2396f97ca5f5f6e89c2bfb9c6e53a5e9ec064ce2135371c928a4028836acd5c` |

## 6. 发布前验证

- 后端完整测试：222项通过。
- 前端组件测试：8个文件、29项通过。
- SSE UTF-8字节分片测试：通过。
- Vite正式构建：通过。
- Python依赖一致性：`pip check`通过。
- Alembic：`0005_user_role (head)`。
- `corpus_v1`一致性：27份文档、103个Chroma片段，`passed_with_warnings`仅保留既有短片段警告。
- `eval_v1`静态校验：40题，分类14/8/6/8/4，来源覆盖27/27。
- 有效真实排序报告Schema：40题、4套候选，通过。
- MySQL只读复核：27份文档；40道评估问题在消息表匹配0条。
- `git diff --check`：通过；Windows仅提示未来检出时可能进行LF/CRLF转换，不是内容错误。

## 7. 后续操作闸门

本审计步骤本身没有执行`git add`、`git commit`、`git push`，也没有连接服务器。用户审查本清单并明确确认后，Git发布步骤才能：

1. 按本清单暂存候选文件并再次查看暂存差异。
2. 创建单一、可回滚的`RAG v1.2.1`里程碑提交。
3. 推送到GitHub并记录提交SHA。

服务器同步仍是后续独立闸门：必须先确认线上当前提交并备份MySQL、Chroma、上传文件和Redis持久数据，然后才能拉取指定提交和重建容器。不得使用`docker compose down -v`，不得在服务器直接编辑业务代码。
