# 对话式资料 Agent 产品与技术设计

> 设计版本：Agent Chat v3.0
>
> 状态：`[发布候选；13.2～13.7已实现，13.8线上发布验收中]`
>
> 目标：在不破坏现有 RAG、资料治理和受控 LangGraph 内核的前提下，把独立任务工作台升级为类似 Codex 的对话式 Agent 工作空间。

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

## 3. 目标界面

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

### 13.8 验收与发布 `[进行中]`

- 完整权限、状态机、幂等、停止、预算、故障和移动端验收。
- 普通RAG完整回归。
- 真实模型调用必须另行通过费用闸门。
- 发布前备份MySQL、文件、Chroma和Redis。
- 验收通过后冻结为`Agent Chat v3.0`。

本地发布候选证据：后端完整336项、前端10个文件35项、独立SSE解析、正式构建、
Python编译与依赖检查通过；1440、1280和390真实浏览器覆盖三栏布局、移动抽屉及
消息/来源/产物三类显式引用，均无整页横向溢出或控制台错误。以上使用临时SQLite、
Fake Planner和Mock工具，未调用Embedding、Reranker或Qwen。

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

## 15. 后续但不属于 v3.0

- 高风险写工具的人工确认节点。
- 后台任务队列和跨进程断点恢复。
- 可插拔Skill与管理员工具授权。
- 受控网页搜索。
- 临时私有附件和对象存储。
- 多Agent协作。
- 可视化工作流编辑器。

这些能力必须在对话式单Agent稳定后逐项评估，不能与阶段13同时开发。
