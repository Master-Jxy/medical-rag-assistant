# Agent Chat v3.0 发布审计

## 范围

阶段13在既有受控LangGraph运行层之上新增按用户隔离的thread/message会话层和
Codex式工作台。普通RAG、资料审核、质量反馈、记忆治理、冻结向量检索基线和五个
Agent工具白名单不变。

## 本地发布候选

- `0018_agent_threads_messages`新增thread/message及run可空关联，旧独立run不回填。
- `AgentConversationApplication`编排消息、run、独立SSE、最终持久化、停止、失败与重试。
- 上下文按当前任务、显式消息/来源/产物、最近8条消息、滚动摘要和已启用记忆组合。
- 幂等键和thread生成锁使用独立命名空间；进程重启遗留非终态记录收敛为稳定失败。
- 前端提供会话、消息/执行过程、来源/产物三栏，移动端改为双抽屉；用户可显式选择
  历史消息、来源和产物继续下一轮，并能切换活动/归档会话和恢复归档会话。
- 后端完整336项、前端10个文件36项、SSE解析、Vite生产构建、Python编译、
  `pip check`通过；Alembic单一head为`0018_agent_threads_messages`。
- 1440、1280、390真实浏览器无整页横向溢出；移动抽屉、三类显式引用可达，控制台
  无错误。

## 安全与成本边界

- thread/message/run/step/artifact读写继续从当前JWT用户过滤。
- metadata只允许来源、产物、显式引用、错误和停止原因，不保存隐藏推理或原始模型响应。
- 同一消息至多创建一个run，同一thread不能并行执行两个run；旧run API继续可用。
- 本地候选只使用Fake Planner、Mock工具和临时SQLite，Embedding、Reranker、Qwen调用
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

- 候选`b81ad5d`已推送至GitHub并通过已校验Git bundle快进服务器；已校验的前端构建
  已替换，backend/web已重建，数据库为`0018_agent_threads_messages (head)`。
- 四容器健康，HTTPS健康200、HTTP固定308；文档/提交/版本27/27/27、Chroma 103和
  旧Agent run/step/artifact 6/6/0保持不变，新thread/message为0。
- 免费生产黑盒覆盖认证、thread CRUD/归档、空消息、跨用户404、未认证401和旧run兼容，
  临时账号与会话均精确清理。发布期间现有用户新增2条普通RAG消息，予以保留。
- 受控浏览器直接访问生产公网IP超时；本地三尺寸UI证据和生产静态资源哈希有效，但生产
  页面交互仍需在最终验收账号中补齐。
- 费用预检确认Qwen3-Max配置、凭据存在和DashScope DNS/TLS可用；没有调用模型。

## 待完成

- 真实三轮最多3次Qwen、0次Embedding/Reranker，单run及累计费用上限均为¥0.05，
  每轮120秒并临时关闭自动重试；必须先获得用户当次明确确认。
- 验收数据与精确幂等键按用户边界清理，并恢复正式重试2；全部证据通过后冻结版本。
- 全部通过后把阶段13与本审计冻结为`Agent Chat v3.0`。
