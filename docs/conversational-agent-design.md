# 对话式资料 Agent 产品与技术设计

> 设计版本：Agent Chat v3.1
>
> 状态：`[v3.1 已完成并上线]`
>
> 目标：保留 v3.0 的会话、运行、审计和预算能力，修复消息顺序、旧入口、聊天体验和任务路由，使 Agent 成为聊天优先、过程可见、工具按需调用的工作空间。

第 1～15 节记录 Agent Chat v3.0 的设计和发布事实；第 16 节是当前唯一有效的
v3.1 演进方案。两者发生冲突时，以第 16 节和 `docs/handoff.md` 为准。

## 1. 产品定位

新版 Agent 不是普通聊天框，也不是展示隐藏推理过程的调试器。它是一个面向医学资料学习与整理的对话式工作空间：

```text
自然语言对话
+ 可见执行计划
+ 受控工具循环
+ 历史会话
+ 来源追溯
+ 报告产物
+ 停止、失败和费用边界
```

用户可以连续提出任务：

```text
用户：检索高血压相关资料，并比较其中两份主要文档。
Agent：完成检索和比较，给出来源。

用户：把刚才的结果整理成学习报告。
Agent：复用上一轮文档和比较结果，生成可下载报告。

用户：再根据报告出 5 道复习题。
Agent：在当前会话上下文内继续工作。
```

普通 RAG 继续负责快速知识问答；Agent 负责需要规划、多个工具步骤、连续追问和产物输出的复杂任务。两者共享状态为 `published` 的公共知识，但保持独立页面、接口、状态和故障边界。

## 2. 设计原则

### 2.1 保留现有内核

现有能力继续复用：

- `AgentApplicationService`：一次运行的创建、执行、停止和持久化。
- `BoundedAgentGraph`：分类、规划、选工具、执行、检查结果和结束。
- `ToolRegistry`：只允许调用白名单工具。
- `agent_runs`、`agent_steps`、`agent_artifacts`：运行、步骤和产物。
- 最多 5 步、单工具超时、整次超时、Token 上限和费用上限。
- 用户隔离、Telemetry、SSE 和安全错误。

本阶段不重写工具，不合并普通 RAG，不更换检索算法，也不把 Agent 改成任意代码执行器。

### 2.2 聊天是交互层，运行是执行层

```text
Agent Thread
-> 多条用户/助手消息
-> 一条用户任务消息触发一个 Agent Run
-> Run 内部执行一个或多个 Step
-> Run 可以生成零个或多个 Artifact
```

一条会话可以包含多次运行；一次运行仍然有明确的开始、结束、预算和审计边界。

### 2.3 展示“工作过程”，不展示隐藏思维

允许展示：

- “正在理解任务”
- “已制定 3 步计划”
- “检索到 4 份资料”
- “正在比较 2 份文档”
- “结果不足，补充检索 1 次”
- “已生成学习报告”
- 工具名称、公开参数摘要、耗时、来源、状态和费用

禁止展示或持久化：

- Chain-of-Thought
- scratchpad
- 模型隐藏推理 Token
- 内部系统 Prompt
- 密钥、服务器路径、SQL、Traceback
- 未经脱敏的第三方异常

### 2.4 用户必须能控制

用户可以：

- 新建、重命名、归档和删除自己的 Agent 会话。
- 查看自己的历史消息、运行、步骤、来源和产物。
- 停止正在运行的 Agent。
- 对失败或停止的用户消息重新运行。
- 显式引用前一轮消息、来源文档或产物继续工作。
- 控制用户长期记忆是否启用，并查看、修改或删除记忆。

系统不能：

- 静默执行无限循环。
- 因页面刷新丢失已经持久化的会话和运行状态。
- 把一个用户的会话、产物或运行泄露给其他用户。
- 把普通聊天历史全部无限塞入模型。

## 3. v3.0 历史界面设计

### 3.1 桌面布局

```text
┌──────────────────────────────────────────────────────────────────────┐
│ AppShell / 面包屑 / Agent 状态 / 当前账号                           │
├──────────────┬──────────────────────────────────┬────────────────────┤
│ Agent 会话   │ 对话与执行时间线                 │ 上下文与产物       │
│              │                                  │                    │
│ + 新建会话   │ 用户消息                         │ 本轮引用来源       │
│ 搜索         │ Agent 公开计划                   │ 选中文档           │
│ 历史会话     │ 工具调用折叠卡                   │ Markdown 报告      │
│ 置顶/归档    │ 流式最终回答                     │ 下载与追溯         │
│              │                                  │                    │
│              │ 固定底部输入区                   │ 可折叠             │
└──────────────┴──────────────────────────────────┴────────────────────┘
```

稳定尺寸建议：

- 左侧会话栏：`240px`，可折叠。
- 中间工作区：`minmax(0, 1fr)`，正文阅读宽度建议不超过 `880px`。
- 右侧上下文栏：`320px`，无内容时折叠，不留下空白占位。
- 输入区固定在中间工作区底部，不覆盖最后一条消息。

### 3.2 移动布局

390 宽移动端：

- Agent 会话列表进入左侧抽屉。
- 来源与产物进入右侧抽屉或底部全屏面板。
- 中间只保留消息、执行状态和输入区。
- 工具步骤默认折叠，避免信息密度压垮小屏。
- 停止按钮始终可达，但不能遮挡输入内容。

### 3.3 消息类型

中间时间线只显示以下用户可理解的消息：

1. **用户消息**：任务、补充要求或追问。
2. **Agent 状态消息**：正在规划、执行、停止或失败。
3. **计划卡**：公开的 1～5 步计划，可以折叠。
4. **工具卡**：工具名称、状态、结果摘要、耗时和来源数量。
5. **最终回答**：流式 Markdown、引用来源和免责声明。
6. **产物卡**：文件名、类型、生成时间、来源和下载按钮。
7. **系统提示**：预算耗尽、超时、功能关闭或权限不足。

不使用大面积嵌套卡片。计划和工具过程属于一条 Agent 消息的可展开区域，不再额外套多层装饰容器。

### 3.4 输入区

第一版输入区包含：

- 多行文本输入。
- 发送按钮。
- 运行中停止按钮。
- `@` 引用当前会话中的来源文档或产物。
- 快捷任务菜单：检索、摘要、比较、学习报告。

第一版不允许把本地附件绕过资料审核直接写入公共知识库。资料上传继续进入“我的资料 -> 管理员审核 -> 发布”链路。未来如增加“仅当前会话临时附件”，必须建立独立隔离存储、过期清理和模型费用边界，不能复用公共发布接口。

## 4. 黑盒数据流

### 4.1 新建会话

```text
用户点击“新建会话”
-> Vue 调用 POST /agent/threads
-> AgentThreadService 创建当前用户的 thread
-> MySQL 保存标题、状态和时间
-> 前端进入该 thread
-> 显示空状态和输入框
```

### 4.2 发送第一条任务

```text
用户发送任务
-> API 校验 thread 归属和消息内容
-> MessageService 保存 user message
-> AgentConversationService 创建 agent_run
-> run 关联 thread_id 和 trigger_message_id
-> LangGraph 开始循环
-> SSE 返回计划、工具、进度、Token 和最终回答
-> assistant message 与 artifact 持久化
-> thread 更新时间和标题摘要更新
```

### 4.3 连续追问

```text
用户说“把刚才结果改成表格”
-> ContextBuilder 读取当前 thread
-> 先保留最近消息
-> 再加入滚动摘要
-> 加入用户显式记忆
-> 加入上一轮引用文档和产物 ID
-> 在 Token 预算内生成本轮 Agent 输入
-> 创建新的 run
-> Agent 根据已有上下文继续执行
```

“刚才”“这个报告”“前两份资料”等指代必须通过显式消息、来源和产物引用解析，不能只依赖模型猜测。

### 4.4 页面刷新

```text
浏览器刷新
-> 读取 thread 列表
-> 读取当前 thread 消息
-> 读取关联 run/step/artifact 摘要
-> 如果 run 仍在运行，显示“运行状态待确认”
-> 查询 run 最新状态
-> 恢复消息、来源、产物和停止/重试按钮
```

第一版不宣称跨进程断点续跑。后端进程重启时，已有运行必须进入明确的 `failed` 或 `stopped` 恢复状态，不能永久停在 `running`。

## 5. 数据模型

### 5.1 新增 `agent_threads`

建议字段：

| 字段 | 说明 |
| --- | --- |
| `id` | UUID |
| `user_id` | 所属用户，所有查询必须过滤 |
| `title` | 自动生成或用户修改，最大长度受限 |
| `status` | `active/archived` |
| `summary` | 更早消息的滚动摘要，不包含隐藏推理 |
| `summary_until_message_id` | 摘要覆盖到哪条消息 |
| `last_message_at` | 会话排序 |
| `created_at/updated_at` | 时间字段 |

### 5.2 新增 `agent_messages`

建议字段：

| 字段 | 说明 |
| --- | --- |
| `id` | UUID |
| `thread_id` | 所属 Agent 会话 |
| `user_id` | 冗余归属字段，用于防御性过滤 |
| `role` | `user/assistant/system` |
| `content` | 用户可见文本 |
| `status` | `pending/streaming/completed/failed/stopped` |
| `run_id` | 可空；助手消息关联本轮运行 |
| `reply_to_message_id` | 可空；显式回复某条消息 |
| `metadata` | 受控 JSON，只保存引用和界面状态 |
| `created_at/updated_at` | 时间字段 |

`metadata`只允许白名单键，例如：

- `source_ids`
- `artifact_ids`
- `referenced_message_ids`
- `error_code`
- `stop_reason`

禁止保存任意模型原始响应或隐藏推理字段。

### 5.3 扩展现有 `agent_runs`

新增可空字段：

- `thread_id`
- `trigger_message_id`
- `response_message_id`

关系：

```text
agent_threads 1 -> N agent_messages
agent_threads 1 -> N agent_runs
agent_messages 1 -> 0..1 agent_runs
agent_runs 1 -> N agent_steps
agent_runs 1 -> N agent_artifacts
```

现有历史运行不删除。迁移后可以：

- 保持 `thread_id = NULL`，在“旧版独立任务”筛选中只读展示；或
- 为当前用户创建一个“历史独立任务”线程并批量关联。

第一版优先采用可空兼容方案，避免一次性重写生产历史。

### 5.4 删除与归档

- 删除 thread 必须级联删除其 messages、runs、steps、artifacts 和会话摘要。
- 删除只允许当前用户操作自己的 thread。
- 归档只改变可见状态，不删除运行证据。
- 下载产物必须同时校验 artifact -> run -> thread -> user 归属。
- 真实删除前需要确认；失败时返回稳定错误和 `request_id`。

## 6. 后端模块边界

建议在现有 `modules/agent` 内增加：

```text
modules/agent/
|-- thread_models.py
|-- thread_repository.py
|-- thread_schemas.py
|-- thread_service.py
|-- message_service.py
|-- context_builder.py
|-- conversation_application.py
`-- existing run/graph/tool files
```

职责：

- `AgentThreadService`：会话增删改查、归档和标题。
- `AgentMessageService`：消息持久化、状态转换和归属。
- `AgentContextBuilder`：在预算内组合最近消息、摘要、记忆和引用。
- `AgentConversationApplication`：编排消息、run、SSE和最终持久化。
- `AgentApplicationService`：继续只负责一次 run，不承担会话管理。
- `AgentRepository`：继续拥有 run/step/artifact。

固定依赖方向：

```text
Agent API
-> AgentConversationApplication
-> Thread/Message Service + AgentApplicationService
-> Repository / Context Port / Knowledge Port / Model Port
```

禁止：

- 在 Vue 中拼接上下文。
- 让 ThreadService 直接查询 Chroma。
- 让 Agent 工具直接读取消息表或用户记忆表。
- 把 RAG `ConversationChatService` 直接改造成 Agent 服务。
- 建立同时管理 thread、run、知识库、用户和模型的万能 Service。

## 7. 上下文与记忆策略

### 7.1 上下文优先级

按以下顺序分配 Token 预算：

1. 当前用户消息。
2. 当前任务显式引用的消息、文档和产物。
3. 最近 6～10 条可见消息。
4. 当前 Agent 会话滚动摘要。
5. 用户已启用的显式长期记忆。
6. 工具定义和系统安全约束。

如果预算不足，从低优先级内容开始裁剪；不能裁掉当前任务、安全约束和显式引用。

### 7.2 会话摘要

- 复用阶段十二的提取式摘要思想，不额外保存隐藏推理。
- 摘要只概括用户目标、已确认事实、使用过的来源和生成产物。
- 摘要更新失败不能阻断当前回答；记录安全错误并继续使用最近消息。
- 删除 thread 时摘要一起删除。

### 7.3 用户长期记忆

- 默认关闭。
- 只读取用户主动保存且启用的记忆。
- Agent不能自动把医疗结论写入长期记忆。
- 用户关闭记忆后，新运行不再读取；删除后不得保留隐蔽副本。

## 8. API 契约

### 8.1 Thread

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/api/v1/agent/threads` | 新建会话 |
| `GET` | `/api/v1/agent/threads` | 当前用户会话列表 |
| `GET` | `/api/v1/agent/threads/{id}` | 会话详情 |
| `PATCH` | `/api/v1/agent/threads/{id}` | 重命名或归档 |
| `DELETE` | `/api/v1/agent/threads/{id}` | 删除自己的会话 |

### 8.2 Message 与执行

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/v1/agent/threads/{id}/messages` | 分页读取历史消息 |
| `POST` | `/api/v1/agent/threads/{id}/messages/stream` | 保存用户消息并启动流式Agent |
| `POST` | `/api/v1/agent/runs/{id}/stop` | 停止运行，复用现有接口 |
| `POST` | `/api/v1/agent/messages/{id}/retry` | 对失败/停止的用户消息重新运行 |

现有 `/api/v1/agent/runs` 查询接口在迁移期保留，供旧页面兼容和运行详情读取。新页面不再要求用户先创建 run 再单独调用 stream，而由 Conversation Application 在一条消息请求内完成编排。

### 8.3 分页

- thread 列表使用游标或稳定的 `last_message_at + id` 排序。
- messages 使用游标向前加载，首屏只返回最近一页。
- run 步骤和 artifact 可以随当前消息按需加载。
- 不允许每次打开页面读取全部历史消息和全部步骤。

## 9. SSE 事件

新版会话 SSE 保留现有执行事件，并增加消息边界：

| 事件 | 用途 |
| --- | --- |
| `message_created` | 用户消息和占位助手消息已经持久化 |
| `run_started` | 本轮运行开始 |
| `plan_ready` | 用户可见执行计划 |
| `tool_started` | 工具开始 |
| `tool_completed` | 工具完成或失败摘要 |
| `token` | 最终回答增量文本 |
| `sources` | 本轮来源 |
| `artifact_ready` | 产物已持久化并可下载 |
| `run_completed` | 运行完成及计量 |
| `message_completed` | 助手消息持久化完成 |
| `stopped` | 安全停止 |
| `error` | 稳定错误码和 `request_id` |

前端状态机：

```text
idle
-> creating_message
-> planning
-> running_tools
-> streaming_answer
-> completed | stopped | failed
```

网络断开时，前端不凭本地内容宣布完成；重新查询 message/run 状态后恢复。

## 10. 前端结构

建议拆分：

```text
features/agent-chat/
|-- AgentThreadSidebar.vue
|-- AgentConversation.vue
|-- AgentMessageItem.vue
|-- AgentRunProgress.vue
|-- AgentPlanPanel.vue
|-- AgentToolTimeline.vue
|-- AgentContextDrawer.vue
|-- AgentArtifactList.vue
|-- AgentComposer.vue
|-- useAgentThread.js
|-- useAgentStream.js
`-- agentEventReducer.js
```

`AgentView.vue`只负责页面组合，不继续堆积API、SSE解析、运行状态、下载和所有交互。

交互要求：

- 新消息发送后立即出现，但标记为“提交中”；服务端确认后再固定 ID。
- 同一 thread 同一时间只允许一个 active run。
- 运行中输入区可以保留草稿，但不能再触发第二个并行 run。
- 停止后允许继续发送新消息。
- 工具步骤默认折叠，失败步骤自动展开。
- 来源点击打开当前系统已有原文预览和PDF页码定位。
- 产物下载沿用当前认证下载接口。

## 11. 安全与成本

- thread、message、run、step、artifact所有读写都从当前JWT用户过滤。
- thread ID、message ID和artifact ID均不可作为授权依据。
- 一次消息只创建一次run，使用幂等键防止双击和网络重试重复扣费。
- 同一thread使用生成锁，防止并发运行污染上下文。
- Agent继续执行最多5步；未来提高上限必须重新评估费用和失控风险。
- 真实模型调用前继续计算Token/费用并检查停止条件。
- 工具失败只把安全摘要交给规划器，不传入Traceback。
- 不记录完整Prompt、隐藏推理和医学正文到Telemetry。
- 普通用户上传资料仍需审核；Agent只检索`published`资料。
- 第一版不执行网页搜索、系统命令、任意Python/SQL、文件写入或医疗诊断。

## 12. 兼容与迁移

### 12.1 不破坏现有能力

以下回归必须保持：

- `/chat`普通RAG页面和SSE不变。
- 已有Agent run/step/artifact可查询和下载。
- 已发布27份资料和Chroma基线不重复向量化。
- 阶段9资料审核、阶段12质量/记忆/治理不改变。
- Agent功能开关关闭时普通RAG继续可用。

### 12.2 旧页面迁移

开发顺序：

1. 先新增thread/message后端，不删除旧API。
2. 再增加新聊天页面并通过功能开关访问。
3. 新页面验收后，把旧运行历史作为兼容入口或筛选项。
4. 最后决定是否删除旧任务表单代码；删除前必须有运行详情回归。

不做一次性大重写。

## 13. 开发任务

### 13.0 设计冻结 `[本文件]`

- 固定产品定位、数据模型、API、SSE、UI和安全边界。
- 更新项目入口文档，删除“Agent永远不是聊天式交互”的旧决策。
- 不修改代码、不调用模型、不部署。

### 13.1 Thread 与 Message 持久化 `[完成]`

- Alembic新增`agent_threads/agent_messages`。
- 扩展`agent_runs`关联字段。
- Repository按用户隔离，补级联删除和旧run兼容测试。
- 不改前端、不调用模型。

实际实现使用`0018_agent_threads_messages`，旧run关联字段保持可空且不回填；消息
`metadata`只允许来源、产物、显式引用、错误和停止原因白名单，不保存模型原始响应或
隐藏推理。本任务完成时后端326项通过，未增加API、SSE、前端或模型调用。

### 13.2 会话服务与上下文构建器 `[完成]`

- 实现thread/message用例。
- 实现最近消息、摘要、显式记忆和引用的预算组合。
- 使用Fake Planner验证“刚才结果”等连续引用。
- 不改LangGraph工具白名单。

### 13.3 对话API与SSE `[完成]`

- 增加thread/message接口和新版事件。
- 使用幂等键和thread生成锁。
- 保留旧run接口。
- 补网络断开、停止、失败和刷新恢复测试。

### 13.4 Run关联与连续任务 `[完成]`

- 一条用户消息创建一次run。
- 最终回答保存为assistant message。
- 来源、步骤和artifact与消息关联。
- 支持失败/停止消息受控重试。

### 13.5 Codex式前端骨架 `[完成]`

- 实现三栏布局、thread列表、消息区和输入区。
- 把现有run历史、步骤和产物改造成消息内可展开组件。
- 完成1280/1440和390响应式检查。

### 13.6 过程、来源与产物联动 `[完成]`

- 流式展示计划、工具状态和最终回答。
- 右侧上下文栏展示来源、PDF页码和产物。
- 支持从消息中引用已有来源和产物继续提问。

### 13.7 连续对话与旧数据兼容 `[完成]`

- 验证多轮上下文、滚动摘要和用户记忆开关。
- 旧版独立run保持可查看。
- 验证删除thread清理所有专属数据且不影响公共知识。

### 13.8 验收与发布 `[完成]`

- 完整权限、状态机、幂等、停止、预算、故障和移动端验收。
- 普通RAG完整回归。
- 真实模型调用已在当次费用确认后按闸门完成。
- 发布前备份MySQL、文件、Chroma和Redis。
- 已通过受控验收并冻结为`Agent Chat v3.0`。

本地与发布证据：最终后端完整340项、前端10个文件36项、独立SSE解析、正式构建、
Python编译与依赖检查通过；1440、1280和390真实浏览器覆盖三栏布局、移动抽屉及
消息/来源/产物三类显式引用，均无整页横向溢出或控制台错误。以上使用临时SQLite、
Fake Planner和Mock工具，未调用Embedding、Reranker或Qwen。

生产费用闸门把自动重试临时设为0，同一thread完成3轮
`generate_learning_report`，分别使用2362、2361、3245 Token，估算费用
¥0.014905、¥0.0149025、¥0.0142175，累计¥0.044025；Embedding与Reranker均为0次。
第三轮用户消息显式关联第二轮产物，最终6条消息、3个run、3个step和3个Markdown产物
的终态、来源与关联一致。验收后临时账号和精确Redis键全部清理，正式重试恢复2。

真实验收发现两个候选期Mock未覆盖的集成问题并在冻结前修复：确定性安全路由现在只
判断`[当前任务]`，不会被系统安全说明中的禁用词误拒绝；完整预算化上下文仍通过
`AgentToolContext.task_context`进入报告工具，使最近消息和显式产物摘录真正参与内容
生成。生产桌面自动化因受控浏览器未发出登录请求、Windows控制无法可靠确认URL而没有
形成可重复证据；不把该限制伪报为生产UI通过，本地同构三尺寸UI、生产静态资源哈希及
生产REST/SSE黑盒共同作为界面与链路证据。

## 14. 验收标准

### 14.1 产品验收

- 用户能新建多个Agent会话，刷新和重新登录后历史仍存在。
- 同一会话至少完成3轮连续任务，并正确引用上一轮文档或产物。
- 用户能看到公开计划、工具状态、来源、产物、停止和错误，不看到隐藏推理。
- 历史会话支持重命名、归档和删除。
- 页面在1280/1440桌面与390移动端没有不可解释遮挡或整页横向溢出。

### 14.2 技术验收

- 所有thread/message/run查询按当前用户隔离。
- 双击发送和网络重试不会生成两个run或重复付费。
- 同一thread不能并发运行两个Agent任务。
- 停止、超时、Token和费用上限均形成稳定终态。
- 页面刷新可以从服务端恢复消息和运行结果。
- 删除thread后其消息、运行、步骤和产物无残留。
- 普通RAG、资料审核、质量反馈、记忆和知识治理完整回归。

### 14.3 面试可讲述结果

完成后可以真实描述：

> 系统使用LangGraph实现受步骤、超时、Token和费用约束的工具循环，并在其上增加按用户隔离的Agent线程与消息模型。前端采用对话式工作台，通过SSE实时展示公开计划、工具状态、流式回答、来源和报告产物；上下文由最近消息、滚动摘要、显式记忆及引用产物按预算组合，同时通过幂等、生成锁和权限校验避免重复调用与跨用户数据泄露。

## 15. v3.0 发布时的后续候选

- 高风险写工具的人工确认节点。
- 后台任务队列和跨进程断点恢复。
- 可插拔Skill与管理员工具授权。
- 受控网页搜索。
- 临时私有附件和对象存储。
- 多Agent协作。
- 可视化工作流编辑器。

这些能力必须在对话式单Agent稳定后逐项评估，不能与阶段13同时开发。

## 16. Agent Chat v3.1 产品修复方案 `[已完成]`

### 16.1 为什么先修产品主链路

2026-07-26 对当前代码、线上截图和历史设计复核后确认，v3.0 已经具备可用的
thread/message/run/step/artifact 分层，但交互仍像“任务调试台”，没有达到稳定聊天产品
的体验：

1. `agent_messages` 只按 `created_at + UUID` 排序。用户消息和助手占位消息在同一事务、
   同一秒内创建时，MySQL 时间精度可能相同，随机 UUID 不能表达先后关系，页面刷新后
   可能出现助手回复排到用户问题上方。
2. 前端仍加载 `thread_id IS NULL` 的旧独立 run，并保留“旧版独立任务”入口，使会话
   模型和旧任务模型同时成为用户入口。
3. 桌面端固定三栏，右侧“来源与产物”长期占据宽度；来源 UUID、英文终态和执行卡片
   抢占回答正文的阅读位置。
4. `classify_and_plan` 只有“允许后选工具”和“拒绝后结束”两条主路由。“你是谁”、
   “不错”等无需工具的消息也可能进入知识检索，产生无意义来源甚至失败。
5. 当前 LangGraph 已经允许 `inspect_result -> select_tool` 循环，实际工具次数可以少于
   5；但页面和文案把它表现成固定计划，用户容易误以为每次必须执行 5 步。

本阶段不新增业务工具，不修改普通 RAG、资料审核或知识库内容。先把消息顺序、对话
路由、聊天呈现和旧数据退出做正确，再继续人工确认或高风险写工具。

### 16.2 对照成熟系统后的取舍

本项目借鉴原则，不整体引入或照搬其他平台：

- LangGraph Agent Chat UI：线程、实时消息、工具调用和 interrupt 都属于同一会话。
- LangGraph 持久化与 interrupt：`thread_id` 是恢复运行的持久游标，高风险动作可以在
  保存状态后暂停，而不是依赖浏览器一直在线。
- Open WebUI：聊天是主入口，历史、知识检索、工具和引用按需接入同一对话；来源附着
  在回答上，不用永久空白侧栏承载。
- assistant-ui：UI、会话运行时和模型后端分层；工具调用以有稳定 ID 的消息部件呈现，
  线程列表独立负责创建、切换、归档和删除。
- Codex：thread 承载连续任务，进度和工具调用在任务中逐步更新；高风险动作显式审批，
  最终结果和产物仍回到对应消息。

本机旧课程项目也完成了定向复核：其Streamlit页面用`st.chat_message`按user/assistant
顺序呈现，`create_agent`让模型在工具结果后继续选择下一动作，值得借鉴“聊天优先”和
“模型-工具-观察”循环。但历史只在`st.session_state`，后端每次只发送当前query，没有
数据库线程、用户隔离、幂等、停止恢复、预算、审计和持久产物，因此不能复制其整体
架构。本项目只吸收交互节奏和循环思想，继续保留现有企业工程边界。

不会直接替换为 assistant-ui 或 LangChain Agent Chat UI。本项目继续使用 Vue 3 和现有
FastAPI API，只吸收其状态分层、事件归并、工具内联和按需面板思想。

调研入口：

- [LangGraph Agent Chat UI](https://docs.langchain.com/oss/python/langgraph/ui)
- [LangGraph event streaming](https://docs.langchain.com/oss/python/langgraph/event-streaming)
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [Open WebUI Chat & Conversations](https://docs.openwebui.com/features/chat-conversations/)
- [Open WebUI History & Search](https://docs.openwebui.com/features/chat-conversations/chat-features/history-search/)
- [Open WebUI RAG and citations](https://docs.openwebui.com/features/chat-conversations/rag/)
- [assistant-ui architecture](https://www.assistant-ui.com/docs/architecture)
- [assistant-ui threads](https://www.assistant-ui.com/docs/runtimes/concepts/threads)
- [assistant-ui tools](https://www.assistant-ui.com/docs/tools)
- [OpenAI Codex app](https://openai.com/index/introducing-the-codex-app/)

### 16.3 v3.1 产品布局

桌面端固定为两栏，不再永久显示“来源与产物”第三栏：

```text
┌────────────────────────────────────────────────────────────────────┐
│ AppShell / 当前页面 / 连接状态 / 当前账号                          │
├────────────────┬───────────────────────────────────────────────────┤
│ Agent 会话     │ 当前会话                                          │
│                │                                                   │
│ + 新建会话     │ 用户消息                                          │
│ 活动 / 归档    │ Agent 最终回答                                    │
│ 搜索与历史     │ ├─ 执行过程（默认折叠，运行中自动展开）            │
│ 会话菜单       │ ├─ 引用来源（文件名、页码、相关片段）              │
│                │ └─ 产物（文件卡、下载、继续引用）                  │
│                │                                                   │
│                │ 固定底部输入区 / 引用标签 / 发送或停止             │
└────────────────┴───────────────────────────────────────────────────┘
```

具体规则：

- 视觉结构复用 `/chat` 的两栏比例、消息留白、滚动区和输入区，不复制其业务逻辑。
- 用户消息始终在右，Agent 消息始终在左；一条助手消息只出现一次。
- 回答正文是主内容。执行过程、来源和产物属于该条助手消息的 message parts。
- 完成后不显示原始 `completed`；仅在运行、失败、停止时显示中文状态。
- 来源显示文件名、页码和可理解摘要，不把 UUID 当作主要文案。
- 来源详情通过点击后临时抽屉或对话框打开；关闭后不占页面宽度。
- 只有用户主动打开大型报告预览时才出现临时产物面板；普通来源和下载不使用永久右栏。
- 运行中“发送”替换为“停止”，尺寸不变；输入框保留，但同一 thread 不允许并发发送。
- 移动端会话列表进入抽屉，消息和输入区占满主屏；执行过程、来源和产物在消息内展开。
- “旧版独立任务”入口、兼容消息分支和旧任务选择状态全部退出产品页面。

### 16.4 消息顺序与数据模型

`created_at` 只用于显示时间和审计，不能再作为会话内唯一排序真相。新增：

| 字段 | 位置 | 规则 |
| --- | --- | --- |
| `sequence_no` | `agent_messages` | thread 内严格递增的正整数 |
| `turn_id` | `agent_messages` | 同一轮 user/assistant 共用，可空兼容历史 |
| `next_message_sequence` | `agent_threads` | 下一次可分配序号，默认1 |

数据库约束：

- 唯一索引：`UNIQUE(thread_id, sequence_no)`。
- 常用索引：`INDEX(thread_id, sequence_no)`。
- 一轮开始时使用`SELECT ... FOR UPDATE`锁定当前thread，读取
  `next_message_sequence=N`，给用户消息分配`N`、助手占位消息分配`N+1`，再把thread
  计数器更新为`N+2`；三项在同一事务提交或回滚。
- 禁止先查消息`MAX(sequence_no)`再无锁加1。
- 历史回填优先使用run的`trigger_message_id/response_message_id`把user/assistant配成
  一轮，再按轮的创建时间排序；无法关联的system或异常历史消息才使用
  `created_at/id`稳定兜底。回填完成后把thread计数器设为`MAX(sequence_no)+1`。
- 回填只用于建立新真相，不把 UUID 继续用作日常排序。
- 消息列表、最近上下文、滚动摘要和分页游标统一按 `sequence_no`。
- API 返回 `sequence_no` 和 `turn_id`；前端只按 `sequence_no` 渲染。

需要增加同一时间戳的回归用例：强制 user 和 assistant 使用完全相同的 `created_at`，
刷新、分页、最近上下文和摘要都必须保持 user 在前、assistant 在后。SQLite 单独通过
不算完成；迁移和排序至少要覆盖一次真实 MySQL 契约。

### 16.5 前端事件归并

页面不能继续依靠“服务端消息数组 + optimistic 数组 + 临时助手数组”按位置拼接。
建立单一 timeline store/reducer：

```text
REST 历史 -> 按 message_id 建立实体 -> 按 sequence_no 排序
SSE message_created -> 写入/更新 user 与 assistant 实体
SSE run/step/source/artifact -> 按 run_id、step_id、artifact_id 更新对应助手消息部件
SSE token -> 只追加到 assistant_message_id
SSE terminal -> 收敛同一助手消息状态
刷新 -> REST 重建相同实体，不重复 append
```

每个事件必须携带足以关联的稳定 ID：

- 消息：`message_id`、`sequence_no`、`turn_id`。
- 运行：`run_id`、`assistant_message_id`。
- 工具：现有稳定 `step_id`，前端把它视为 `tool_call_id`。
- 来源：`document_id + chunk_id + page`。
- 产物：`artifact_id`。

Reducer 对相同 ID 做幂等更新，不根据事件到达先后制造第二个气泡。断线重连、刷新恢复
和终态回放必须得到相同时间线。

### 16.6 Agent 路由与动态工具循环

第一节点不再只返回 `allowed`，而是返回以下明确意图：

| `route` | 适用场景 | 工具次数 |
| --- | --- | --- |
| `direct_reply` | 问身份、能力、边界、礼貌反馈和无需资料的说明 | 0 |
| `clarification` | 缺少文档、比较对象、目标或关键参数 | 0 |
| `tool_required` | 必须检索、读取、摘要、比较或生成报告 | 1～上限 |
| `refuse` | 诊断、处方、越权写入、系统命令等禁用请求 | 0 |

新黑盒流程：

```text
用户消息
-> route_task
   -> direct_reply -> 直接生成用户可见回答 -> finalize
   -> clarification -> 提出一个明确补充问题 -> finalize
   -> refuse -> 返回稳定安全边界 -> finalize
   -> tool_required
      -> 模型选择一个白名单工具
      -> 参数校验和预算检查
      -> 执行工具
      -> 模型读取公开观察结果
         -> 已足够：finalize
         -> 信息不足：更换参数或选择下一个工具
         -> 需要用户：clarification
         -> 工具失败：受控回退、澄清或 fail
```

`max_steps=5` 保留，但统一解释为“单次运行最多 5 次工具调用”的安全上限，实际可以是
0～5 次。公开计划允许在执行过程中更新，但不要求预先填满 5 步。系统不展示或持久化
隐藏思维，只展示计划摘要、工具名、安全参数摘要、状态、耗时和结果摘要。

v3.1 先在现有 `AgentPlanner`/`ToolRegistry`/LangGraph 边界内增加路由和循环语义，不在
同一步把整个内核替换为 `create_agent`。后续只有在同一固定任务集上证明原生 function
calling 的稳定性、预算和错误契约不低于当前实现，才考虑替换规划适配器。

### 16.7 旧版独立任务退出

`agent_runs/agent_steps/agent_artifacts` 仍是当前 threaded Agent 的执行与审计数据，不能
删除表或关闭全部 run 查询。只退出 `thread_id IS NULL` 的旧独立任务：

1. 前端删除 `legacyRuns`、`legacySelected`、`selectLegacy` 和侧栏旧任务区域。
2. 停止暴露创建无 thread run 的用户入口；当前会话创建 run 的内部应用服务继续使用。
3. 增加一次性维护脚本，默认 `--dry-run` 输出旧 run、step、artifact 和文件数量。
4. 只有显式 `--confirm` 且完成数据库与产物目录备份后，才删除 `thread_id IS NULL`
   的 run 及其专属 step/artifact/file。
5. 清理后再次证明所有 `thread_id IS NOT NULL` 的消息、run、step、artifact 数量和引用
   不变。

生产清理不是 Alembic 自动动作，不随容器启动执行。没有用户当次确认时，只提交脚本和
Mock/临时数据库测试，不删除线上记录。

### 16.8 模块边界

前端建议边界：

```text
AgentView.vue                 # 页面编排，不处理事件细节
features/agent-chat/
|-- AgentThreadSidebar.vue    # 会话创建、切换、归档、菜单
|-- AgentConversation.vue     # 时间线容器和滚动
|-- AgentMessageItem.vue      # 用户/助手消息外壳
|-- AgentExecutionParts.vue   # 计划与工具步骤
|-- AgentSourceParts.vue      # 消息内来源
|-- AgentArtifactParts.vue    # 消息内产物
|-- AgentDetailDrawer.vue     # 按需来源/产物详情
|-- AgentComposer.vue
|-- useAgentTimeline.js       # 实体化 reducer 与稳定排序
|-- useAgentThread.js
`-- useAgentStream.js
```

后端继续遵守：

```text
API -> AgentConversationApplication
    -> AgentThreadRepository
    -> AgentApplicationService / BoundedAgentGraph
    -> AgentPlanner + ToolRegistry
    -> 公开业务 Port
```

- API 不决定 route、不直接删旧数据。
- ConversationApplication 负责编排一轮消息与 run，不实现工具。
- Repository 负责 sequence 分配、查询和持久化，不拼前端卡片。
- Planner 只产生显式业务决策，不返回隐藏推理。
- 工具仍只能调用公开应用 Port，不能直接访问 SQL、Chroma 或系统命令。
- 来源、产物和步骤继续归属 run/assistant message，不变成前端全局状态。

### 16.9 开发顺序

开发必须按以下顺序，一次只完成一个可回退小任务：

1. **14.1 消息顺序基线**：迁移 `next_message_sequence/sequence_no/turn_id`、基于run
   关系的确定性回填、thread行锁序号预留、Repository/API/MySQL回归。未通过前不改页面。
2. **14.2 旧入口退役**：删除前端 legacy 分支，关闭无 thread 创建入口，加入只针对
   `thread_id IS NULL` 的 dry-run 清理脚本；不执行生产删除。
3. **14.3 两栏聊天外壳**：复用 RAG 视觉结构，移除永久右栏，先用现有 API 渲染。
4. **14.4 时间线 reducer**：REST/SSE 统一按实体 ID 和 sequence 合并，覆盖重连、刷新、
   重复事件和乱序事件。
5. **14.5 任务路由**：实现 direct reply、clarification、tool required、refuse；问候、
   身份和正面反馈不得调用知识工具。
6. **14.6 动态工具循环**：把执行次数明确为按需 0～5 次，补工具失败后的受控反馈与
   选择，保持预算、停止和审计。
7. **14.7 完整验收**：权限、排序、状态、响应式、可访问性、普通 RAG 回归和固定 Agent
   场景集。
8. **14.8 生产清理与发布**：备份、迁移、发布、在线无费用检查；生产旧数据清理和真实
   模型验收分别获得当次确认后执行。

高风险写工具的人工确认节点顺延到 v3.1 稳定之后，避免在错误时间线和旧入口仍存在时
增加新状态。

### 16.10 v3.1 验收标准

产品验收：

- 连续发送 20 轮并刷新，消息顺序始终与创建顺序一致。
- “你是谁”“你好”“不错”均零工具调用、零来源，返回自然直接回答。
- 检索、摘要、比较和报告按需要执行不同数量工具，不凑固定步数。
- 回答正文优先；执行过程、来源、产物附着在对应助手消息并可折叠。
- 桌面没有永久右侧上下文栏；移动端没有整页横向滚动、遮挡或不可达按钮。
- 页面不存在“旧版独立任务”入口和旧任务专用气泡。

技术验收：

- 数据库唯一约束保证 thread 内 `sequence_no` 无重复，分页和上下文统一按其排序。
- 同时间戳、重复 SSE、乱序 SSE、断线重连和刷新回放均不重复或交换消息。
- 同一用户消息至多一个 run；直接回答和澄清允许 0 step run。
- 每个 tool step 与唯一助手消息、run 和稳定 step ID 关联。
- 旧记录清理脚本默认只读；确认清理只影响 `thread_id IS NULL` 数据。
- 旧数据清理前后 threaded message/run/step/artifact、公共知识、RAG 会话均保持不变。
- 普通 RAG、认证、资料审核、管理中台、记忆、质量和部署健康回归通过。

费用与发布：

- 14.1～14.7 默认使用 Fake Planner、Mock 工具和临时数据库，不调用 Qwen、Embedding
  或 Reranker。
- 任何真实模型验收先给出调用数、预计费用、超时、自动重试和清理方案，并取得当次确认。
- 文档完成不等于功能完成；README 和简历只能在代码、测试和发布验收后更新为 v3.1。
