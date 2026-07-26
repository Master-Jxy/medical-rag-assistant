# Agent Chat v3.0 发布审计

## 范围

阶段13在既有受控LangGraph运行层之上新增按用户隔离的thread/message会话层和
Codex式工作台。普通RAG、资料审核、质量反馈、记忆治理、冻结向量检索基线和五个
Agent工具白名单不变。

## 本地与生产发布内容

- `0018_agent_threads_messages`新增thread/message及run可空关联，旧独立run不回填。
- `AgentConversationApplication`编排消息、run、独立SSE、最终持久化、停止、失败与重试。
- 上下文按当前任务、显式消息/来源/产物、最近8条消息、滚动摘要和已启用记忆组合。
- 幂等键和thread生成锁使用独立命名空间；进程重启遗留非终态记录收敛为稳定失败。
- 前端提供会话、消息/执行过程、来源/产物三栏，移动端改为双抽屉；用户可显式选择
  历史消息、来源和产物继续下一轮，并能切换活动/归档会话和恢复归档会话。
- 最终后端完整340项、前端10个文件36项、SSE解析、Vite生产构建、Python编译、
  `pip check`通过；Alembic单一head为`0018_agent_threads_messages`。
- 1440、1280、390真实浏览器无整页横向溢出；移动抽屉、三类显式引用可达，控制台
  无错误。

## 安全与成本边界

- thread/message/run/step/artifact读写继续从当前JWT用户过滤。
- metadata只允许来源、产物、显式引用、错误和停止原因，不保存隐藏推理或原始模型响应。
- 同一消息至多创建一个run，同一thread不能并行执行两个run；旧run API继续可用。
- 发布前本地候选只使用Fake Planner、Mock工具和临时SQLite，Embedding、Reranker、Qwen调用
  均为0，费用为0。

## 生产发布前证据

- 生产发布前提交为`97a9d10e17ee`，工作树干净，数据库为
  `0017_knowledge_governance`，四个容器健康，HTTPS健康200。
- 发布前基线：5个账号、5个普通RAG会话、92条普通消息、27份文档、27份已发布提交、
  27个版本、103个Chroma片段、6个旧Agent run、6个step、0个artifact、26个Redis键。
- 全量备份`/home/deploy/medical-rag-backups/backup-20260726T084026Z`包含MySQL、
  `app_data`、`chroma_data`、`redis_data`和部署配置；7项SHA-256全部通过，目录权限700、
  文件权限600。

## 生产候选部署

- 候选行为基线`6f5e7a8`已推送至GitHub并通过已校验Git bundle快进服务器；已校验的前端构建
  已替换，backend/web已重建，数据库为`0018_agent_threads_messages (head)`。
- 四容器健康，HTTPS健康200、HTTP固定308；文档/提交/版本27/27/27、Chroma 103和
  旧Agent run/step/artifact 6/6/0保持不变，新thread/message为0。
- 免费生产黑盒覆盖认证、thread CRUD/归档、空消息、跨用户404、未认证401和旧run兼容，
  临时账号与会话均精确清理。发布期间现有用户新增2条普通RAG消息，予以保留。
- 受控浏览器可以加载生产登录页和静态资源，但提交登录时没有发出
  `/api/v1/auth/login`请求；服务器访问日志确认请求未到达应用。Windows界面兜底又因
  无法可靠确认当前浏览器URL而安全中止。因此没有把生产UI自动化写成已通过；本地
  1440/1280/390真实浏览器、生产静态资源哈希和生产REST/SSE黑盒共同保留为证据。
- 费用预检确认Qwen3-Max配置、凭据存在和DashScope DNS/TLS可用；没有调用模型。

## 真实三轮验收

- 用户在当次对话确认最多3次Qwen、0次Embedding/Reranker、0次自动重试、每轮120秒、
  单run与累计费用均不超过¥0.05。生产`DASHSCOPE_MAX_RETRIES`由2临时改为0并经容器
  配置复核后开始执行。
- 第一次正式消息在模型调用前被确定性路由拒绝：预算上下文中的系统安全说明包含
  “开处方/系统命令”等词，旧逻辑误把完整上下文当成当前用户任务。该run为0 step、
  0 Token、¥0，未调用Qwen；临时账号、thread和Redis键立即精确清理。
- 修复提交`05872fe`让确定性允许/拒绝与工具路由只读取`[当前任务]`，完整上下文仍交给
  模型；新增两项回归后，定向15项与后端完整340项通过并部署。
- 前两轮报告真实执行后，审计确认确定性报告工具虽然收到当前任务，却没有把最近消息和
  显式产物摘录传入内容生成器。提交`bee1ee7`为`AgentToolContext`增加预算化
  `task_context`并由报告工具传给生成Port；定向21项、后端完整340项通过后部署。
- 最终同一thread的三轮`generate_learning_report`均为单step完成，SSE包含
  `message_created/run_started/plan_ready/tool_started/tool_completed/sources/
  artifact_ready/token/run_completed/message_completed`。三轮分别使用2362、2361、
  3245 Token，费用¥0.014905、¥0.0149025、¥0.0142175，合计7968 Token、¥0.044025；
  Qwen共3次，Embedding/Reranker/自动重试均为0。
- 第三轮用户消息显式引用第二轮产物，最终6条message、3个run、3个step和3个Markdown
  artifact的用户归属、来源、响应消息和终态全部一致。所有报告只引用已发布文档
  `c7177cc7-0fa0-4599-ad5b-0a5c03c90261`。

## 清理、恢复与冻结

- 临时验收账号、1个thread、6条message、3个run、3个step、3个artifact，以及3个精确
  幂等键、用户限流键和thread生成锁均清理为0；其他用户数据未删除。
- `DASHSCOPE_MAX_RETRIES`恢复2并重建后端。最终生产为5个既有账号、5个普通RAG会话、
  94条普通RAG消息、27/27/27文档/提交/版本、103个Chroma片段、27个上传文件、
  6/6/0个既有旧run/step/artifact和0个新thread/message。
- 数据库保持`0018_agent_threads_messages (head)`，四容器健康，HTTPS健康200、HTTP
  固定308，生产源码工作树干净；代码行为提交为`bee1ee7`。
- 阶段13与本审计据此冻结为`Agent Chat v3.0`。生产UI控制工具限制作为已知验收环境
  缺口保留，不改变REST/SSE、多轮持久化、费用和清理结论。
