# RAG 离线评估资产

本目录只保存版本化的语料元数据、评估集和后续基线报告，不连接线上会话，也不保存文档正文。

- `corpora/corpus_v1.json`：27 份本机公共文档与 103 个 Chroma 片段的元数据快照。文件和片段只保存 SHA-256、长度、ID 等校验信息。
- `schemas/evaluation_set_v1.schema.json`：后续 30～50 道评估题必须遵守的数据结构。
- `schemas/baseline_report_v1.schema.json`：离线 Runner 输出的版本化报告结构。
- `categories_v1.json`：`eval_v1` 的五类题目及 40 题目标配额。
- `datasets/eval_v1.json`：基于 `corpus_v1` 原文编写的 40 道固定评估题，同时绑定语料版本和 `corpus_checksum`。
- `reviews/eval_v1_review.md`：只展示题目、类别、行为和来源文件名的人工审查清单。
- `reports/dry_run_v1.json`：假检索、假回答产生的可重复干跑报告，仅验证 Runner 和指标计算。
- `reports/current_baseline_v1.json`：用户明确确认后完成的40题当前系统真实基线；全部题目完成，报告不保存问题或回答正文。
- `reviews/current_baseline_v1_review.md`：真实基线的指标、异常题和评分限制复核摘要。
- `reports/human_review_capture_v1.json`：第二次有界运行的无正文结构化报告，不覆盖首次基线。
- `schemas/rag_comparison_report_v1.schema.json`：三套候选方案的配置指纹、评估结果和分阶段计量契约。
- `schemas/rag_comparison_plan_v1.schema.json`：真实候选对比前的冻结产物、调用次数、Token、费用和停止条件契约。
- `reports/rag_v1_2_mock_comparison_v1.json`：三套候选的确定性Mock对比，只验证归因、Schema和指标算术。
- `reports/rag_v1_2_real_comparison_v1.json`：用户确认后完成的三套方案真实对比；冻结基线没有重跑，两个新候选各运行40题，报告不含正文。
- `reviews/rag_v1_2_real_comparison_v1_summary.md`：真实质量、延迟、Token、费用、评分限制和生产方案决定。
- `schemas/retrieval_ranking_report_v1.schema.json`：任务7.7候选池实验的四套Profile、配置指纹、逐题文档级排序指标和分类汇总契约。
- `schemas/retrieval_ranking_plan_v1.schema.json`：共享检索真实排序的冻结资产、价格快照和硬预算契约。
- `schemas/retrieval_ranking_real_report_v1.schema.json`：不含正文的真实排序质量、阶段失败/回退和调用计量契约。
- `reports/retrieval_ranking_mock_v1.json`：候选池12、每文档最多2片段、最终4片段的确定性Mock报告；只验证策略与指标算术，不代表真实收益。
- `plans/retrieval_ranking_preflight_v1.json`：任务7.7第二小步的原始只读真实排序计划；首次无效尝试后已由恢复计划取代，不得再次用于授权。
- `plans/retrieval_ranking_recovery_preflight_v2.json`：绑定首次无效尝试、追加费用和累计硬上限的恢复计划。
- `reports/retrieval_ranking_real_v1_invalid_vector_port_20260721.json`：首次真实运行的无效审计产物；向量阶段40题全部本地失败，不得用于晋级。
- `reviews/retrieval_ranking_invalid_attempt_20260721.md`：无效原因、费用计量、修复和恢复闸门说明。
- `reports/retrieval_ranking_real_v1.json`：用户重新确认后完成的有效40题检索排序报告；不含问题、回答或文档正文。
- `reviews/retrieval_ranking_real_v1_summary.md`：四套排序指标、费用、预登记门槛和不晋级决定。
- `plans/rag_v1_2_preflight_v1.json`：当前版本化运行计划；绑定公开价格、冻结产物和执行硬上限，真实执行仍要求再次确认。
- `reviews/human_review_capture_v1_decisions.json`：40题人工行为与关键事实决策，不含回答正文。
- `reviews/human_review_capture_v1_summary.md`：自动评分和人工语义复核差异及已知局限。

评估题的 `expected_source_document_ids` 必须引用 `corpus_v1` 中存在的文档 ID；`expected_key_facts` 只写用于评分的简短事实，不复制整篇文档。评估运行结果以后保存到独立报告，不写入 MySQL 用户会话。

从 `backend` 目录执行只读一致性检查：

```powershell
.venv\Scripts\python.exe -m scripts.build_corpus_manifest --check
.venv\Scripts\python.exe -m scripts.validate_evaluation_set
.venv\Scripts\python.exe -m scripts.run_fake_evaluation
.venv\Scripts\python.exe -m scripts.run_current_baseline
.venv\Scripts\python.exe -m scripts.run_mock_comparison
.venv\Scripts\python.exe -m scripts.preflight_rag_v1_2_comparison
.venv\Scripts\python.exe -m scripts.run_rag_v1_2_comparison
.venv\Scripts\python.exe -m scripts.run_mock_retrieval_ranking
.venv\Scripts\python.exe -m scripts.run_real_retrieval_ranking
```

静态校验会检查 `corpus_checksum`、总数、分类配额、题号和问题去重、来源存在性、单/多文档来源数量、连续追问历史、拒答无来源，以及回答题的来源和关键事实。语料内容变化但版本名不变时也会拒绝运行。

假适配器干跑固定注入一个检索失败、一个回答失败和一个计量缺失，用于验证失败隔离、评分分母和费用完整性；其中的 `1.0` 指标不代表真实 RAG 质量。关键事实自动分数采用规范化后的精确子串匹配，可能低估真实回答中的同义改写，后续报告必须保留评分方法名称并支持人工复核。上述命令均不运行 Chroma、模型或 Embedding，也不写 MySQL 会话。

RAG v1.2 Mock对比固定登记向量基线、向量+关键词RRF、向量+关键词RRF+Rerank三套完整配置及SHA-256指纹，并强制使用同一 `eval_v1` 和语料checksum。它补充分阶段耗时、Embedding保守计量、Rerank Token/费用和总费用完整性，但固定黄金返回产生的质量1.0只证明报告流程正确。真实计划复用冻结基线，不重复付费，两个新候选的最坏上限为80次Embedding、80次Qwen、40次Rerank、148万Token和4.4元；4.4元是立即停止的总硬上限，不是预计实际费用。按2026-07-19中国内地公开单价和当前基线计量估算整轮约0.6～1.0元。

完整预检命令默认只读取当前MySQL文档登记、文件、Chroma、版本化评估资产和本地配置，不创建Embedding、Qwen或Rerank客户端，也不联网验证密钥权限：

```powershell
.venv\Scripts\python.exe -m scripts.run_rag_v1_2_comparison
```

2026-07-19预检得到 `plan_sha256=8dc58c5988ae51f0afde5df576e408318082663813a276c5bf9d8b640aa00249`。只有用户在看到最新预检、价格和预算后重新确认，才允许执行一次：

```powershell
.venv\Scripts\python.exe -m scripts.run_rag_v1_2_comparison --execute --confirm-paid-run RUN_RAG_V1_2_COMPARISON_V1 --confirm-plan-sha256 8dc58c5988ae51f0afde5df576e408318082663813a276c5bf9d8b640aa00249
```

命令会先再次完整预检；计划文件变化会使SHA确认失效，同名正式报告存在时拒绝覆盖。两个候选共享全局预算且零自动重试：失败调用按最坏情况保留预留并隔离当前题，成功调用缺失计量或任何次数、Token、费用上限无法容纳下一次调用时立即停止，不发布不完整正式报告。

2026-07-19的唯一一次真实候选对比已经完成，正式报告存在后命令会拒绝再次运行。两个新候选合计估算费用0.622606元，40次Rerank均成功；但两者的来源平均召回率和完整来源命中率都与冻结向量基线完全相同，延迟和费用更高。因此生产混合检索与Reranker继续关闭，当前向量基线保持启用；详细解释见 `reviews/rag_v1_2_real_comparison_v1_summary.md`。

任务7.7第一小步的 `scripts.run_mock_retrieval_ranking` 只在内存中构造固定假片段，使用纯 `CandidateSelectionPolicy` 和文档级指标生成可重复报告；不会读取Chroma、模型配置密钥或业务数据库。Mock报告不保存问题、回答、Prompt、文件名或片段正文，空期望来源题的排序指标全部为 `null` 并从平均值分母排除。四套Mock质量差异是人为固定排序的算术验证，不能用于晋级或生产决策。

任务7.7第二小步的 `scripts.run_real_retrieval_ranking` 默认只做无费用预检。首次真实运行暴露真实工厂装配错误：40题向量阶段均在远程Embedding调用前失败，关键词与Reranker各执行40次，因此报告已改名保留为无效审计产物，不能用于晋级。Reranker使用246713输入Token、估算0.1973704元；无效报告0.20761元的保守总数另含未实际调用的Embedding预留。修复后真实存储先包装为`CurrentChromaKnowledgeSearchAdapter`，并新增全向量失败禁止发布保护。

恢复计划SHA-256为 `72b18169399f8805d9384d688585b74250230c4bd3cc38dced19dff6b1c012e4`；恢复轮预计追加0.2～0.6元、单轮硬上限1.1元，包含首次尝试的累计硬上限1.31元。用户已在看到恢复预算后重新确认，并通过确认短语和计划哈希完成唯一一次恢复运行；正式报告存在后命令禁止再次执行。

用户重新确认后恢复运行已完成：40题向量、关键词和Reranker全部成功，0次Qwen；有效轮估算0.151674元，两次运行合计保守估算0.359284元。文档配额候选的多文档Recall@4只提高0.041667，未达到0.05；两个混合候选总体Recall@4从0.919643回退到0.904762。没有候选满足晋级门槛，生产继续使用向量基线，两项实验开关保持关闭，不再运行完整回答评估。

`scripts.run_current_baseline` 默认也只做只读预检：重新比对 MySQL 文档登记、磁盘文件、Chroma 与 `corpus_v1`，检查40题 checksum、103个片段、模型名、密钥是否配置、固定 `top_k=4`、零重试和硬预算；不会联网验证密钥，也不会调用 Embedding 或 Qwen。真实运行必须同时提供：

```powershell
.venv\Scripts\python.exe -m scripts.run_current_baseline --execute --confirm-paid-run RUN_CURRENT_BASELINE_V1
```

真实运行最多40次查询向量化和40次 Qwen 调用，模型输出每题最多2048 Token；总 Token 预算50万、预计费用硬上限2元，任何调用次数、Token、费用或计量缺失条件触发后立即停止且不写不完整报告。适配器只读取现有 Chroma 并使用进程内临时上下文，不调用会话 Service，不创建用户、会话或消息，不写 MySQL 或 Chroma。2026-07-18 的首次运行已完成；不要在未确认新预算时重复执行付费命令。

## 本地人工复核

包含模型回答正文的复核文件只能放在被 Git 忽略的 `backend/evaluation/local_reviews/`。文件必须绑定 `eval_v1`、`corpus_checksum` 和原始报告 SHA-256，时间包含时区且保留期最多7天；到期后必须删除，不能移动到 `reviews/`、日志、MySQL或其他可提交目录。

每道题的人工行为标注为 `answer/refuse/uncertain`，每条关键事实标注为 `met/not_met/uncertain`。最小结构如下，`answer_text` 只允许出现在上述本地忽略目录：

```json
{
  "schema_version": "local_human_review_v1",
  "dataset_version": "eval_v1",
  "corpus_checksum": "<corpus_v1 checksum>",
  "source_report_sha256": "<current_baseline_v1 SHA-256，小写>",
  "created_at": "2026-07-18T18:00:00+08:00",
  "expires_at": "2026-07-25T18:00:00+08:00",
  "items": [{
    "case_id": "eval_001",
    "answer_text": "<仅本地粘贴回答>",
    "behavior_decision": "uncertain",
    "key_fact_decisions": ["uncertain"],
    "reviewer_notes": ""
  }]
}
```

只读校验和新旧评分对比命令：

```powershell
.venv\Scripts\python.exe -m scripts.validate_local_human_review evaluation\local_reviews\review.json
```

命令不输出问题、回答正文或备注，不连接 MySQL、Chroma、Embedding 或模型。它会拒绝目录外文件、过期文件、超过7天的保留期、未知/重复题号、关键事实标注数量错误，以及与原始报告哈希不一致的文件。

第二次捕获运行使用独立命令和确认短语，产物存在时会直接拒绝，不能覆盖或重复付费运行：

```powershell
.venv\Scripts\python.exe -m scripts.run_human_review_capture --execute --confirm-paid-run RUN_HUMAN_REVIEW_CAPTURE_V1
.venv\Scripts\python.exe -m scripts.apply_local_human_review_decisions evaluation\local_reviews\human_review_capture_v1.json evaluation\reviews\human_review_capture_v1_decisions.json
.venv\Scripts\python.exe -m scripts.validate_local_human_review evaluation\local_reviews\human_review_capture_v1.json --report evaluation\reports\human_review_capture_v1.json
```

2026-07-18 的40题捕获和人工决策已完成；不要再次执行付费捕获命令。本地正文文件于北京时间2026-07-25 20:57:34到期，到期后必须删除。

`review_scoring.py` 提供独立复核方法：拒答使用 `answer/refuse/needs_review` 三态短语分类；同义事实只接受人工审核的概念等价短语组，并单独标记矛盾短语。固定脱敏样例中，替代拒绝措辞从 v1 的 `answer` 变为 v2 的 `refuse`，同义事实覆盖从0变为1；这只是方法验证，不会回写或重算原始报告。
