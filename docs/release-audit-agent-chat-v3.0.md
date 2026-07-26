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
  历史消息、来源和产物继续下一轮。
- 后端完整336项、前端10个文件35项、SSE解析、Vite生产构建、Python编译、
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

## 待完成

- 推送并部署发布提交，迁移到`0018`，复查数据基线、HTTPS、普通RAG与新会话黑盒。
- 真实模型调用必须在独立费用闸门后执行；验收数据必须按用户边界精确清理。
- 全部通过后把阶段13与本审计冻结为`Agent Chat v3.0`。
