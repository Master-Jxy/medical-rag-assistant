# 长期记忆与用户额度中心设计

> 状态：阶段17、18本地开发与验证完成，未发布
> 目标阶段：阶段17、阶段18
> 最后更新：2026-07-31

## 1. 目标与边界

本设计在现有模块化单体上增加两项能力：

1. **长期记忆 v2**：在用户主动开启后，从已完成聊天中提取可控、可追溯的长期信息；
   用户能够查看、编辑、拒绝、删除和关闭记忆；普通RAG与Agent只读取和当前问题相关的
   少量记忆。
2. **额度与用量中心**：把阶段16已经记录的实际模型usage组织成用户可理解的回答级
   用量、个人趋势和管理员总览，并在模型调用前完成原子额度预留，防止并发透支。

本阶段不是引入Mem0、LiteLLM或Langfuse整套服务，也不是把项目拆成微服务。现有
FastAPI、MySQL、Redis、Chroma和Docker拓扑继续保留，新增能力通过小型Port接入RAG和
Agent。

明确不做：

- 不保存或展示模型隐藏推理、Prompt、验证码、密码、API Key或完整知识正文。
- 不让普通聊天、记忆提取和额度结算互相直接导入Repository。
- 不做充值、支付、发票、计费结算或真实商业套餐。
- 不在阶段17引入新的向量数据库或为每条记忆复制一份敏感向量。
- 不一次性重写现有会话、Agent、Telemetry或个人中心。
- 不直接复制第三方项目的受限目录、品牌界面或整套服务。

## 2. 开发前基础与本地实现结果

### 2.1 开发前已有记忆能力

当前已经存在：

- `conversation_summaries`：保存较早会话内容的滚动摘要。
- `user_memory_settings`：用户级记忆总开关，默认关闭。
- `user_memories`：用户手工创建、编辑和删除的显式记忆。
- 普通RAG通过`ConversationMemoryService`加载摘要与显式记忆。
- Agent通过`SqlAlchemyAgentMemoryContext`加载已启用记忆。
- 个人中心已经有记忆开关和CRUD入口。

开发前缺口：

- 滚动摘要只是截取并拼接历史消息，不是模型生成的结构化摘要。
- 系统不会自动提取用户背景、偏好、长期目标或正在进行的任务。
- 没有候选、确认、拒绝、冲突、过期、来源和修订历史。
- RAG与Agent使用不同查询实现，排序方向和预算不完全一致。
- 普通RAG读取上下文时会顺便刷新并提交摘要，读操作带有写副作用。
- 当前最多读取20条记忆并直接拼接，未按当前问题做相关性选择。

### 2.2 开发前已有用量能力

阶段16已经建立`model_usage_records`，能够按单次模型调用保存：

- `call_id`、`request_id`和可空`user_id`。
- `surface`、`operation`和`model_name`。
- 输入、输出和总Token。
- `actual`、`unknown`和`not_applicable`计量状态。
- 调用时输入/输出单价快照和估算费用。
- `call_id`幂等写入和删除账号后的用户匿名化。

开发前缺口：

- 只有全局聚合，没有普通用户自己的汇总、趋势和调用明细。
- 一条Agent回答可能有多次模型调用，目前缺少统一的回答级`usage_group_id`。
- 助手消息底部没有本次输入/输出Token、费用和计量状态。
- 没有套餐、周期、已用、预留、剩余额度和重置时间。
- 没有调用前预留，不能从额度角度防止并发透支。
- 管理员不能按用户、模型、入口和时间筛选，也不能受审计地调整额度。
- `ModelUsage`定义在RAG Port中，Usage和Agent反向依赖RAG类型，属于应增量消除的耦合。

### 2.3 本地实现结果

- 阶段17的`0022_memory_v2`、统一`MemoryContextProvider`、候选/来源/冲突/修订、
  相关Top-K、持久化调度和过期任务恢复已完成；健康背景必须确认，调度或提取失败不改变
  原回答终态。
- 阶段18的`0023_usage_groups`、`0024_user_quota`、回答级usage、个人/管理员用量中心、
  MySQL并发预留、过期reservation对账和超级管理员审计调整已完成。
- Fake自动化、完整后端/前端/SSE/构建、MySQL`0021 -> 0024 -> 0021 -> 0024`、
  双线程额度争抢以及1440/1280/390浏览器验收通过。
- 两个功能开关仍默认关闭；没有调用真实模型、SMTP，没有部署、生产迁移或Git提交。

## 3. 总体架构

```text
                           +----------------------+
用户问题 ----------------> | RAG / Agent应用服务 |
                           +----------+-----------+
                                      |
                     +----------------+----------------+
                     |                                 |
                     v                                 v
          MemoryContextProvider                 QuotaApplicationService
                     |                                 |
          只读Top-K相关记忆                    原子预留/结算/释放
                     |                                 |
                     v                                 v
               memory模块                         usage模块
                     |                                 |
              MySQL记忆数据                 MySQL账本与额度周期
                                                       |
                                                 Redis仅作短期缓存

回答完成
-> 保存助手消息
-> 记录回答级usage
-> 创建可恢复的记忆提取任务
-> 后台受控提取候选记忆
-> 用户审核或低风险自动生效
```

固定依赖方向：

```text
API Router
-> Application Service
-> Port / Repository
-> Infrastructure
-> MySQL / Redis / DashScope
```

跨模块规则：

- RAG和Agent只依赖`MemoryContextProvider`，不得读取记忆表。
- RAG和Agent只依赖`QuotaGatePort`与`UsageRecorderPort`，不得计算余额或写额度表。
- memory可以使用`ConversationHistoryPort`读取必要的已完成消息，但不得导入会话Repository。
- memory提取模型通过`MemoryExtractionModelPort`访问，不能直接创建DashScope客户端。
- usage拥有厂商无关的`ModelUsage`契约；RAG、Agent和模型适配器依赖usage契约。
- 管理后台只能调用memory/usage公开查询服务，不能成为跨模块万能Service。
- Redis不是额度真相源。第一版额度的权威预留和结算在MySQL事务中完成。

## 4. 目标目录与增量重构

目标结构用于指导开发，不要求一次性搬完：

```text
backend/app/modules/memory/
|-- models.py
|-- schemas.py
|-- ports.py
|-- repository.py
|-- settings_service.py
|-- lifecycle_service.py
|-- extraction_service.py
|-- retrieval_service.py
|-- summary_service.py
|-- context_provider.py
`-- policies.py

backend/app/modules/usage/
|-- models.py
|-- contracts.py
|-- schemas.py
|-- ports.py
|-- repository.py
|-- recorder.py
|-- query_service.py
|-- quota_service.py
`-- pricing.py

backend/app/infrastructure/
|-- memory_extraction_model.py
`-- quota_cache.py              # 可选，阶段18后半再评估
```

增量迁移要求：

1. 先增加新Port和测试，再移动实现。
2. 原`service.py`保留兼容导出，调用方迁移完成后才删除旧入口。
3. `ConversationMemoryService.context_prefixes()`改为只读；摘要刷新移动到消息完成后的独立
   用例，不能在读取上下文时提交事务。
4. RAG和Agent统一使用同一`MemoryContextProvider`，不再各写一套记忆查询。
5. `ModelUsage`迁入`usage.contracts`时，`rag.ports`暂时重导出兼容类型；调用方全部迁移
   后再移除兼容层。
6. 每个小任务只改变一个主模块；API和SSE契约变化单独成步。

## 5. 长期记忆 v2

### 5.1 三层记忆

| 层级 | 内容 | 生命周期 | 是否用户可编辑 |
| --- | --- | --- | --- |
| 最近消息 | 最近若干轮原始聊天 | 随会话 | 通过删除会话控制 |
| 会话摘要 | 较早聊天的压缩摘要 | 随会话级联删除 | 第一版只读 |
| 长期记忆 | 跨会话背景、偏好、目标和任务 | 用户级 | 是 |

三层分别受独立字符/Token预算约束。优先保留当前问题、最近消息和用户明确引用，再放入
相关长期记忆，最后才放较早会话摘要。

### 5.2 记忆分类

第一版固定分类：

```text
profile             身份与稳定背景
preference          表达、格式和交互偏好
goal                长期目标
ongoing_task        正在进行的任务
health_context      健康背景，敏感
explicit_note       用户明确要求记住的内容
```

禁止提取：

- 密码、验证码、API Key、私钥、SMTP授权码和访问Token。
- 身份证号、银行卡、精确住址等高风险身份信息。
- 来自助手猜测、检索片段或模型推断但未被用户明确表达的事实。
- 临时寒暄、一次性问题、与后续交互无关的短期内容。
- 医疗诊断结论、药物剂量建议和模型自行推断的疾病。

### 5.3 数据模型

阶段17迁移建议使用`0022_memory_v2`。

`user_memory_settings`增量字段：

| 字段 | 含义 |
| --- | --- |
| `enabled` | 总开关；关闭后停止提取和注入 |
| `auto_extract_enabled` | 是否自动生成低风险候选，默认随总开关关闭 |
| `updated_at` | 设置更新时间 |

`user_memories`增量字段：

| 字段 | 含义 |
| --- | --- |
| `category` | 固定分类 |
| `status` | `candidate/active/rejected/expired` |
| `source_type` | `extraction/manual` |
| `confidence` | 可空提取置信度，不作为唯一自动通过依据 |
| `created_by` | `user/system` |
| `normalized_hash` | 用户范围内的去重摘要 |
| `valid_until` | 可空过期时间 |
| `supersedes_id` | 可空冲突或替代关系 |
| `last_used_at` | 最近一次被注入上下文的时间 |

新增`user_memory_sources`，允许一条记忆引用多条RAG或Agent消息：

```text
id
memory_id
surface: rag/agent/profile
thread_id nullable
message_id nullable
created_at
```

该表不复制消息正文。因为普通RAG与Agent使用不同消息表，memory模块不能对两个业务表建立
混合外键；写入时由`MemorySourceReaderPort`验证消息属于当前用户，读取来源时也通过该
Port解析会话标题和可用状态。原会话被删除后来源显示“原会话已删除”，长期记忆本身仍由
用户独立控制。

新增`user_memory_revisions`：

```text
id
memory_id
version_no
label
content
category
status
changed_by
change_reason
created_at
```

新增`memory_extraction_runs`：

```text
id
user_id
surface: rag/agent
thread_id
through_sequence
status: pending/running/completed/skipped/failed
trigger: periodic/explicit/recovery
candidate_count
usage_group_id
error_code
attempt_count
created_at/started_at/completed_at
```

唯一约束`(surface, thread_id, through_sequence)`防止网络重试或进程恢复后重复提取同一
段对话。

### 5.4 自动提取黑盒

触发条件：

- 用户已经开启总开关和自动提取。
- 一轮用户消息与助手消息已经持久化为终态。
- 距上次提取新增达到配置轮数，建议默认3轮；用户明确说“记住……”时立即触发。
- 当前没有同一`conversation_id + through_sequence`任务。

流程：

```text
助手回答完成
-> RAG或Agent完成钩子通过MemoryExtractionSchedulerPort登记pending任务
-> SSE回答正常结束，不等待第二次模型调用
-> 受控后台执行器领取任务
-> MemorySourceReaderPort读取该surface未处理的已完成消息
-> 敏感信息预过滤
-> MemoryExtractionModelPort只返回固定JSON候选
-> Schema校验
-> 去重、冲突、来源和敏感策略
-> 写入candidate或低风险active记忆
-> 写修订历史与模型usage
-> 标记任务completed
```

第一版不增加Celery或消息队列。任务先持久化，使用FastAPI后台执行作为快速路径；进程中断
后，在下一次聊天或应用启动的受控恢复钩子中重新领取过期`pending/running`任务。单任务
最多重试1次，失败只影响记忆更新，不得让已经完成的回答变成失败。

模型必须输出结构化数据：

```json
{
  "candidates": [
    {
      "category": "goal",
      "label": "职业目标",
      "content": "希望寻找Python后端和AI应用开发岗位",
      "confidence": 0.91,
      "sensitive": false,
      "source_message_ids": ["..."]
    }
  ]
}
```

不保存提取Prompt、隐藏推理和完整模型原始响应。解析失败时记录稳定错误码和unknown usage，
不得把原始响应写入日志。

### 5.5 候选、冲突与敏感策略

- `health_context`始终进入`candidate`，必须由用户确认后才成为`active`。
- 低风险分类只有在来源全部是用户消息、Schema合法、未命中敏感规则、置信度达到阈值且
  没有冲突时，才允许自动成为`active`。
- 新事实与已有事实冲突时不覆盖旧值；新建`candidate`并通过`supersedes_id`关联。
- 内容哈希重复时更新时间和来源，不新增重复卡片。
- 用户手工编辑始终写一条revision；删除主记录时revision按用户删除策略级联清除。
- 关闭记忆提供两个明确动作：“停止使用并保留”和“停止使用并清空全部长期记忆”。

### 5.6 相关记忆检索

第一版不为敏感记忆复制Chroma向量。因为单用户记忆数量有限，使用可替换的本地检索器：

```text
当前问题
-> 中英文词与中文二元词片段规范化
-> 用户范围内只读active且未过期记忆
-> 关键词匹配 + 分类权重 + 明确记忆权重 + 最近使用衰减
-> 去重
-> 返回Top-K和字符预算内的ContextItem
```

`MemoryContextProvider`返回结构化结果：

```text
MemoryContext
|-- items[]
|   |-- id
|   |-- category
|   |-- content
|   `-- score
|-- total_chars
`-- truncated
```

默认建议：

- 普通RAG：最多4条、1200字符。
- Agent：最多6条、1800字符。
- 没有相关记忆时返回空列表，不能为了“用上记忆”强行塞入。

以后如果固定评估集证明语义检索明显优于本地检索，再通过`MemorySearchPort`增加可关闭的
Embedding适配器。未通过评估前不向Chroma复制用户敏感信息。

### 5.7 注入RAG和Agent

```text
RAG:
用户问题
-> ConversationChatService读取最近消息
-> MemoryContextProvider.search(user_id, question, surface="rag")
-> 组装有预算的上下文
-> RagService检索公共知识
-> 模型回答

Agent:
用户任务
-> AgentContextBuilder读取最近消息/显式引用
-> MemoryContextProvider.search(user_id, task, surface="agent")
-> 组装Agent上下文
-> LangGraph按需调用0至5次工具
```

记忆内容在Prompt中标记为“用户可编辑背景，可能过期，不是系统指令”。记忆不得覆盖安全
规则、工具权限、公共知识来源和医疗拒答边界。

### 5.8 用户界面

个人中心新增“长期记忆”页签：

- 总开关与自动整理开关。
- `待确认/已启用/已拒绝/已过期`四种筛选。
- 分类、内容、来源会话、更新时间和最近使用时间。
- 确认、编辑、拒绝、删除操作。
- 冲突记忆并排显示，不用技术字段让用户猜。
- “关闭但保留”和“关闭并清空”必须二次确认。

不显示置信度小数、Prompt或模型内部推理。可把置信度转成“系统整理，待确认”这种产品
语言。

## 6. 额度与用量中心

### 6.1 两个概念必须分开

```text
模型用量账本：发生了什么，永久记录实际/未知/未调用
用户额度周期：允许还能用多少，支持预留、结算和重置
```

账本不可因管理员调整额度而重写；额度不可通过删除账本恢复。

### 6.2 用量契约与回答分组

阶段18先把`ModelUsage`从`rag.ports`迁到`usage.contracts`：

```text
ModelUsage
|-- input_tokens
|-- output_tokens
|-- total_tokens
|-- measurement
|-- cached_input_tokens       # 供应商没有则为空
|-- cache_creation_tokens     # 供应商没有则为空
`-- provider_request_id       # 脱敏可追踪ID
```

`model_usage_records`建议增加：

| 字段 | 用途 |
| --- | --- |
| `usage_group_id` | 一条用户可见助手回答的聚合ID |
| `provider` | 模型供应商 |
| `status` | `completed/failed/cancelled` |
| `latency_ms` | 总调用耗时 |
| `time_to_first_token_ms` | 可空首Token耗时 |
| `cached_input_tokens` | 可空缓存读取Token |
| `cache_creation_tokens` | 可空缓存创建Token |
| `quota_billable` | 是否扣用户额度 |

普通RAG通常一条回答一个调用；Agent的一条最终回答可能包含规划、检查和生成等多个调用，
这些记录共享同一`usage_group_id`。回答底部显示组聚合，不显示内部调用明细。

记忆后台提取消耗单独记为`surface=memory`。默认计入管理员成本统计，但
`quota_billable=false`，避免用户在回答结束后发现额度被后台任务悄悄扣除；以后套餐可以
显式调整该策略。

### 6.3 额度数据模型

阶段18建议迁移拆成`0023_usage_groups`和`0024_user_quota`，避免一次迁移同时改变计量和
额度行为。

新增`quota_plans`：

```text
id
code
name
period_type: daily/weekly/monthly
token_limit
request_limit
estimated_cost_limit_cny nullable
enabled
created_at/updated_at
```

新增`user_quota_assignments`：

```text
user_id
plan_id
token_limit_override nullable
request_limit_override nullable
valid_from/valid_until
updated_by nullable
updated_at
```

新增`quota_periods`：

```text
id
user_id
period_start/period_end
token_limit
request_limit
used_tokens
reserved_tokens
used_requests
reserved_requests
created_at/updated_at
```

`(user_id, period_start, period_end)`唯一。周期边界按`Asia/Shanghai`计算后以UTC保存。

新增`quota_reservations`：

```text
id
idempotency_key
user_id
quota_period_id
surface
usage_group_id
reserved_tokens
charged_tokens
status: reserved/settled/released/expired
expires_at
created_at/settled_at
```

管理员修改套餐或额度必须写现有审计模块，审计只保存变更前后数值、操作者和原因。

### 6.4 调用前预留与调用后结算

第一版使用MySQL行锁保证额度真相，不把余额只放Redis：

```text
用户发送问题
-> QuotaApplicationService根据入口取得最大输出和保守输入估算
-> SELECT FOR UPDATE锁定当前quota_period
-> 检查 used + reserved + 本次预留 是否超限
-> 创建reservation并增加reserved
-> 提交事务
-> RAG或Agent调用模型
-> 每次模型调用写model_usage_records
-> 聚合usage_group
-> 再次锁定period和reservation
-> 用实际Token结算并退回差额
-> SSE done返回回答级用量与剩余额度
```

失败策略：

| 场景 | 处理 |
| --- | --- |
| 调用前额度不足 | 不调用模型，返回`QUOTA_EXCEEDED` |
| 模型调用前失败 | 释放全部预留 |
| 模型返回实际usage | 按实际Token结算 |
| 模型已调用但usage未知 | 按保守预留值结算并标记unknown |
| 确定性回答未调用模型 | 释放预留，扣0 |
| 用户停止生成且有usage | 按已返回实际usage结算 |
| 进程中断 | 过期回收任务核对账本后settle或release |
| 重复请求 | 复用同一idempotency reservation，不重复扣减 |

Redis可在后续作为只读统计缓存或短TTL快速拒绝层，但MySQL始终是余额真相。只有压测证明
MySQL成为瓶颈，才引入Redis Lua双层计数与对账任务。

### 6.5 SSE与历史消息

普通RAG与Agent的最终`done`事件兼容增加：

```json
{
  "usage": {
    "measurement": "actual",
    "input_tokens": 1286,
    "output_tokens": 436,
    "total_tokens": 1722,
    "estimated_cost_cny": 0.0062
  },
  "quota": {
    "remaining_tokens": 83450,
    "period_end": "2026-08-31T16:00:00Z"
  }
}
```

字段只允许兼容新增，现有`token/source/done/error`语义不改变。历史消息REST也返回相同的
回答级usage摘要，刷新页面后不能消失。

`unknown`保持明确未知；不能用字符数估算冒充实际Token。额度为了安全可以按预留结算，
但页面必须区分“实际Token”和“额度扣减Token”。

### 6.6 普通用户页面

个人中心新增“用量与额度”：

- 当前周期总额度、已使用、已预留、剩余量和重置时间。
- 今日、7天、30天请求数和输入/输出Token趋势。
- RAG、Agent、记忆整理三类用量分布。
- 按模型统计Token和估算费用。
- 最近调用明细：时间、入口、模型、状态、Token、费用、耗时。
- unknown usage和未配置价格使用明确文案，不显示虚假0。

每条RAG和Agent助手消息底部显示：

```text
输入 1,286 · 输出 436 · 估算 ¥0.0062
```

默认折叠为一行，不抢占回答和引用来源的视觉层级。

### 6.7 管理员页面

管理员“用量管理”页面：

- 总请求、总Token、估算费用、平均耗时、首Token耗时和计量覆盖率。
- 按用户、模型、入口、状态、时间范围筛选。
- Token趋势区分输入、输出和供应商可用时的缓存Token。
- 高消耗用户、额度耗尽用户、unknown usage和失败调用。
- 用户额度详情与调整入口。

只有`admin/super_admin`可查看全站聚合；修改用户套餐或额度建议仅允许
`super_admin`，并要求填写原因和写审计。不得展示问题、回答、Prompt、医学正文和验证码。

## 7. API规划

### 7.1 记忆

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET/PUT | `/api/v1/profile/memory-settings` | 读取或更新记忆设置 |
| GET/POST | `/api/v1/profile/memories` | 分页查询或手工创建 |
| GET/PATCH/DELETE | `/api/v1/profile/memories/{id}` | 详情、编辑或删除 |
| POST | `/api/v1/profile/memories/{id}/approve` | 确认候选 |
| POST | `/api/v1/profile/memories/{id}/reject` | 拒绝候选 |
| DELETE | `/api/v1/profile/memories` | 显式二次确认后清空 |
| GET | `/api/v1/profile/memory-extractions` | 查看最近整理状态 |

### 7.2 用量与额度

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/v1/profile/quota` | 当前周期额度 |
| GET | `/api/v1/profile/usage/summary` | 用户汇总 |
| GET | `/api/v1/profile/usage/trend` | 用户趋势 |
| GET | `/api/v1/profile/usage/records` | 用户自己的调用明细 |
| GET | `/api/v1/admin/usage/overview` | 全站汇总 |
| GET | `/api/v1/admin/usage/trend` | 全站趋势 |
| GET | `/api/v1/admin/usage/users` | 用户额度和消耗列表 |
| GET | `/api/v1/admin/usage/records` | 脱敏调用明细 |
| PUT | `/api/v1/admin/users/{id}/quota` | 超级管理员调整额度 |

所有列表必须分页，时间范围有最大跨度，用户接口强制`user_id=current_user.id`，不得接受
前端传入任意用户ID。

## 8. 开源借鉴与许可证

| 项目 | 借鉴内容 | 使用方式 |
| --- | --- | --- |
| [Mem0](https://github.com/mem0ai/mem0) | 记忆提取、用户隔离、相关检索、历史 | 借鉴算法与生命周期；不部署整套服务 |
| [Letta](https://github.com/letta-ai/letta) | 可查看、可编辑的核心记忆块 | 借鉴产品交互；不复制旧服务 |
| [LiteLLM](https://github.com/BerriAI/litellm) | 预算、模型维度、消费管理 | 借鉴额度模型；不复制enterprise目录 |
| [Langfuse](https://github.com/langfuse/langfuse) | Trace/Generation、用量和延迟分析 | 借鉴统计维度；不部署完整平台 |
| [One API](https://github.com/songquanpeng/one-api) | 用户额度、模型倍率、调用明细 | 只借鉴产品思想，不复制源码/UI |

若后续复用具体代码，必须在提交中记录：

```text
source_repository
source_commit
source_file
license
local_changes
```

只允许复用兼容的MIT、Apache-2.0或BSD代码，并保留LICENSE/NOTICE。禁止复制
`enterprise/`、`ee/`、来源不明代码或带额外品牌保留要求的页面。当前设计阶段没有复制
任何第三方源码。

## 9. 分步开发路线

### 阶段17：自动长期记忆 v2

1. **任务17.1：契约、迁移与兼容层**
   - 新增`0022_memory_v2`、Repository、Port和枚举。
   - 把摘要写入从上下文读取中拆出。
   - 旧记忆迁移为`active/manual`，行为保持不变。
   - 只用Fake，不调用真实模型，不改页面。
2. **任务17.2：提取任务与Fake模型**
   - 建立幂等提取任务、结构化Schema、敏感策略、去重和冲突。
   - 覆盖进程中断、重试、重复事件和解析失败。
3. **任务17.3：记忆生命周期API和个人中心**
   - 完成候选确认/拒绝、修订历史、关闭保留、关闭清空。
   - 完成用户隔离、删除级联和桌面/移动端页面。
4. **任务17.4：统一相关检索与RAG接入**
   - 实现本地Top-K检索和预算。
   - 普通RAG改用统一`MemoryContextProvider`。
   - 记忆关闭时上下文完全不注入。
5. **任务17.5：Agent接入与提取恢复**
   - Agent改用同一Provider。
   - 接入后台快速路径和过期任务恢复。
   - 记忆提取失败不影响原回答终态。
6. **任务17.6：评估、隐私与冻结**
   - 固定记忆提取/去重/冲突/相关检索数据集。
   - 完整后端、前端、SSE、迁移、安全扫描和浏览器验收。
   - 真实提取模型验收另行说明调用次数和费用并取得授权。

### 阶段18：用户额度与用量中心

1. **任务18.1：Usage契约解耦与回答分组**
   - `ModelUsage`迁入usage模块并保留兼容导出。
   - 新增`0023_usage_groups`和回答级聚合、耗时字段。
2. **任务18.2：回答底部计量**
   - RAG/Agent的SSE done与历史消息返回同一usage摘要。
   - 前端显示实际、未知、未调用和未定价四种状态。
3. **任务18.3：个人用量查询**
   - 用户汇总、趋势、分布和明细API。
   - 个人中心完成响应式用量页面。
4. **任务18.4：额度模型与原子预留**
   - 新增`0024_user_quota`、默认免费计划和MySQL行锁预留。
   - 覆盖并发、幂等、停止、失败、unknown和周期重置。
5. **任务18.5：接入RAG和Agent额度闸门**
   - 两条链路共享Quota Port，不互相导入Service。
   - 额度不足时模型调用为0次。
6. **任务18.6：管理员总控台与审计**
   - 聚合、筛选、高消耗/异常用户和额度调整。
   - 超级管理员调整必须写审计。
7. **任务18.7：完整验收与发布**
   - 迁移往返、并发故障注入、SSE、浏览器、备份和恢复。
   - 先无费用生产黑盒；真实模型和部署分别取得当次授权。

阶段17完成后再进入阶段18。阶段18.1不能提前修改阶段17尚未冻结的记忆计量调用方式。

## 10. 测试与验收矩阵

### 10.1 记忆

- 默认关闭时不提取、不注入、不产生模型费用。
- 用户A无法读取、修改、确认或删除用户B的记忆和提取任务。
- 同一消息范围重复触发只生成一个提取任务。
- 敏感健康信息不会未经确认成为active。
- 冲突事实不静默覆盖，删除和清空无隐藏副本。
- RAG与Agent对同一问题取得相同的相关记忆集合，再按各自预算截断。
- 记忆内容不能覆盖系统安全规则或诱导Agent越权调用工具。
- 提取超时、进程中断和模型JSON错误不改变原回答。

### 10.2 额度

- 两个并发请求不能共同穿透仅够一次的额度。
- 重复幂等键不创建第二个reservation或第二次扣费。
- 实际usage小于预留时正确退回差额。
- usage未知、停止、失败和未调用模型分别按设计结算。
- 周期重置边界、时区和管理员调整不改写历史账本。
- 用户只能查看自己的用量；管理员明细不含正文和秘密。
- 刷新后回答底部Token与SSE结束时一致。
- 额度不足时Qwen/Embedding/Reranker调用均为0。

### 10.3 验证层级

- 任务17.1、17.2、18.1、18.4涉及迁移和共享Port，按L2运行完整后端。
- 页面任务运行前端组件测试、SSE测试和正式构建。
- 1440、1280和390宽真实浏览器检查长期记忆、个人用量和管理员用量页。
- 发布任务按L3执行备份、迁移、四容器、HTTPS、数据基线和回滚检查。
- 默认Fake提取模型与Fake Usage；任何真实模型调用必须单独授权。

## 11. 停止条件与回滚

出现以下情况立即停止当前小步：

- 记忆关闭后仍被提取或注入。
- 用户能访问其他用户记忆、额度或调用明细。
- 医疗敏感信息未经确认自动生效。
- 额度预留可能重复扣减或并发透支。
- unknown usage被展示为实际Token，或后台提取被混入回答用量。
- 迁移不能从生产`0021`升级并安全降级。
- 日志、API或Git出现Prompt、验证码、秘密或完整聊天正文。
- 普通RAG、Agent、认证或资料审核接口契约被意外改变。

回滚顺序：

```text
关闭MEMORY_AUTO_EXTRACTION_ENABLED或QUOTA_ENFORCEMENT_ENABLED
-> 保留账本，停止新提取/新预留
-> 回退应用版本
-> 必要时按顺序降级0024、0023、0022
-> 对账未结算reservation与提取任务
-> 回归认证、RAG、Agent和公共知识基线
```

功能开关建议：

```env
MEMORY_AUTO_EXTRACTION_ENABLED=false
MEMORY_EXTRACTION_INTERVAL_TURNS=3
MEMORY_RAG_MAX_ITEMS=4
MEMORY_AGENT_MAX_ITEMS=6
QUOTA_ENFORCEMENT_ENABLED=false
DEFAULT_QUOTA_PLAN_CODE=free
```

开发与迁移完成不等于立即开启生产功能。发布后先保持两个开关关闭，通过无费用黑盒和
数据检查，再分别决定是否启用。

## 12. 新开发窗口读取范围

阶段17的新开发窗口只需：

1. 完整阅读`AGENTS.md`和`docs/handoff.md`。
2. 阅读本文第1至5节、第8至11节，以及当前任务小节。
3. 只读memory、会话完成钩子、RAG/Agent上下文和对应测试。
4. 任务17.1不得修改usage、前端、服务器或调用真实模型。

阶段18开始后改为读取本文第1至4节、第6至11节，只读usage、RAG/Agent计量、SSE、
个人中心/管理员统计和对应测试。

每完成一个小任务，运行对应测试、更新`docs/handoff.md`，只留下一个下一任务。不要从
聊天历史猜测任务编号，也不要全文读取历史发布审计。
