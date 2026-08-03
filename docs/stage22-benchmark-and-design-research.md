# Stage 22 开源对标与设计证据

> 核验日期：2026-08-03  
> 本文记录可复查的设计来源，不代表复制上游代码。当前实现继续采用 Vue 3、FastAPI、
> MySQL、Redis、LangChain/LangGraph 和模块化单体。

## 1. 结论

Stage 22 只吸收成熟项目的机制，不迁移到新的 Agent 平台，也不引入 Celery、Prefect、
Temporal、可视化工作流或自由对话式 Agent 群。适合本项目的方案是：

1. 不同会话可以并发，但同一会话仍只允许一个运行；MySQL 保存持久状态，Redis 只负责
   锁和短期加速。
2. 前端建立按会话隔离的 stream registry，运行、停止、错误、未读都绑定发起时的会话 ID。
3. 多 Agent 只采用有边界的 supervisor/handoff：最多一个主助手和一个协作助手，角色、
   工具、轮数、Token 和输出契约固定，不允许 Agent 自由群聊。
4. 页面只展示公开计划、工具名称、状态和证据，不展示模型隐藏推理、Prompt、scratchpad
   或供应商原始 reasoning event。
5. 系统资料和用户审核发布资料统一进入管理员知识资产生命周期；发布后原提交者不能永久
   删除，管理员替换失败时旧版本必须继续可检索。

## 2. Agent 编排来源

### LangGraph Supervisor

- 仓库：[`langchain-ai/langgraph-supervisor-py`](https://github.com/langchain-ai/langgraph-supervisor-py)
- 许可证：MIT
- 核验文件：
  - [`README.md`](https://github.com/langchain-ai/langgraph-supervisor-py/blob/88859b34017ac3569bbd4a3092c7e77593a0a960/README.md)
  - [`handoff.py`](https://github.com/langchain-ai/langgraph-supervisor-py/blob/88859b34017ac3569bbd4a3092c7e77593a0a960/langgraph_supervisor/handoff.py)
- 借鉴：把 handoff 表达为有 Schema 的工具和显式状态转移；过滤不需要传给下游的历史。
- 不采用：该扩展包、层级 supervisor、并行 handoff 和 Agent 自由对话。

### OpenAI Agents SDK

- 仓库：[`openai/openai-agents-python`](https://github.com/openai/openai-agents-python)
- 许可证：MIT
- 核验文件：
  - [`handoffs.md`](https://github.com/openai/openai-agents-python/blob/fc084ae29cd751b801c2779c9ebd23ff6bad1668/docs/handoffs.md)
  - [`stream_events.py`](https://github.com/openai/openai-agents-python/blob/fc084ae29cd751b801c2779c9ebd23ff6bad1668/src/agents/stream_events.py)
  - [`tracing.md`](https://github.com/openai/openai-agents-python/blob/fc084ae29cd751b801c2779c9ebd23ff6bad1668/docs/tracing.md)
- 借鉴：handoff 输入过滤、动态启用和 raw event/run item/agent update 分层。
- 不采用：迁移 SDK、绑定 OpenAI 模型或默认保存敏感输入输出的 tracing。

### AutoGen 与 CrewAI

- AutoGen：[`microsoft/autogen`](https://github.com/microsoft/autogen)，MIT；参考
  [`_swarm_group_chat.py`](https://github.com/microsoft/autogen/blob/027ecf0a379bcc1d09956d46d12d44a3ad9cee14/python/packages/autogen-agentchat/src/autogen_agentchat/teams/_group_chat/_swarm_group_chat.py)
  的 handoff 目标校验和最大轮数。
- CrewAI：[`crewAIInc/crewAI`](https://github.com/crewAIInc/crewAI)，MIT 条款；参考
  `Task` 输入输出和顺序执行概念。
- 不采用：Swarm、GroupChat、manager Agent、独立运行时、训练和第二套记忆/缓存体系。

### 医疗 Agent

- 仓库：[`Azure-Samples/healthcare-agent-orchestrator`](https://github.com/Azure-Samples/healthcare-agent-orchestrator)
- 许可证：MIT
- 核验文件：
  - [`magentic_chat.py`](https://github.com/Azure-Samples/healthcare-agent-orchestrator/blob/f9abf14177c0c7c6817a990f45ffa19b3a4cd51b/src/magentic_chat.py)
  - [`healthcare_agents.yaml`](https://github.com/Azure-Samples/healthcare-agent-orchestrator/blob/f9abf14177c0c7c6817a990f45ffa19b3a4cd51b/src/scenarios/default/config/healthcare_agents.yaml)
- 借鉴：专家职责、输入要求、工具范围、引用保真、信息不足时回问和人工复核。
- 不采用：肿瘤会诊拓扑、诊疗建议 Agent、FHIR/Azure/Teams 基础设施和提示词式自由交接。

## 3. 聊天与运行状态来源

### Open WebUI

- 仓库：[`open-webui/open-webui`](https://github.com/open-webui/open-webui)
- 许可证：Open WebUI License，存在品牌限制，不复制源码。
- 参考：`backend/open_webui/models/chats.py` 与 `routers/tasks.py` 中聊天和辅助任务分离。

### LibreChat

- 仓库：[`danny-avila/LibreChat`](https://github.com/danny-avila/LibreChat)
- 许可证：MIT
- 核验文件：
  - [`agents/run.ts`](https://github.com/danny-avila/LibreChat/blob/3191f6975a28550f394bfc2d8bc0ab6b941514f6/packages/api/src/agents/run.ts)
  - [`types/runs.ts`](https://github.com/danny-avila/LibreChat/blob/3191f6975a28550f394bfc2d8bc0ab6b941514f6/packages/data-provider/src/types/runs.ts)
- 借鉴：run/step 持久化、断线后以服务器状态恢复、待处理动作显式化。
- 不采用：整个多供应商平台或向前端转发 THINK/reasoning delta。

### LobeHub

- 仓库：[`lobehub/lobehub`](https://github.com/lobehub/lobehub)
- 许可证：LobeHub Community License，衍生分发有限制，不复制源码。
- 参考：AgentRuntime 的步数上限、force-finish、人工批准和流事件处理思想。

## 4. 任务队列来源

- Prefect：Apache-2.0；参考 run 状态、计划/实际开始时间、累计运行时间、并发槽位。
- Celery：BSD-3-Clause；参考有限重试、指数退避和 jitter。
- 当前不引入它们。`AgentRun` 继续承载用户可见运行，`ProcessingJob` 继续承载后台任务，
  两者不得合并成万能表。只有出现多实例 worker、持续积压或可测的数据库轮询瓶颈时，
  才重新评估外部任务队列。

## 5. 知识资产来源

- RAGFlow：Apache-2.0；参考
  [`document_service.py`](https://github.com/infiniflow/ragflow/blob/266837eb337348f7bb1cb7b65ea69c81b17db33a/api/db/services/document_service.py)
  的文档处理状态和元数据治理。
- Dify：附加限制的修改版 Apache-2.0；只参考 parsing/splitting/indexing/completed
  分阶段恢复思想，不复制源码或引入其 Celery 拓扑。
- 长期模型可演进为稳定 Asset、不可变 Revision、派生 Index、active revision 指针；
  Stage 22 先修正当前生命周期和权限，不一次迁移整个知识模型。

## 6. 公开事件安全边界

允许的事件类别：

```text
run_started, plan_published, specialist_selected, handoff_started,
tool_started, tool_finished, evidence_attached, artifact_ready,
run_completed, run_failed, run_stopped
```

事件只允许稳定 ID、序号、状态、公开代码、模板化摘要、工具标签、耗时和来源/产物 ID。
禁止返回或持久化 raw provider event、Prompt、完整 graph state、模型消息对象、患者隐私参数、
工具原始医学正文、reasoning、chain_of_thought、scratchpad、private_thought。

## 7. 许可证与复用规则

本阶段默认只借鉴架构思想。只有 MIT、Apache-2.0 或 BSD 兼容代码确有必要复用时，才在
源码注释和本文登记仓库、固定提交、文件和许可证；GPL/AGPL/SSPL、自定义限制许可证的
源码不得复制。产品 UI、品牌、文案、Logo、数据和截图不得照搬。
