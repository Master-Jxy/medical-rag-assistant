# 额度策略 v2 技术设计

> 状态：已完成并发布，生产shadow观察中，enforce未启用
> 目标阶段：阶段19
> 最后更新：2026-07-31

## 1. 目标

阶段18已经完成模型usage账本、个人/管理员用量页面、月度额度周期、调用前reservation、
调用后结算以及RAG/Agent Quota Gate，但生产仍使用：

```env
QUOTA_ENFORCEMENT_ENABLED=false
```

因此当前10万Token只用于创建和展示额度周期，不会阻止模型调用。阶段19的目标是：

1. 把所有普通账号的默认月额度从10万提高到100万Token。
2. 保留`user/admin/super_admin`三种角色，不增加任何新身份。
3. 增加`off/shadow/enforce`三级模式，先观察再正式拦截。
4. 用保守动态预留替换RAG固定4000 Token预留。
5. 同时支持Token硬上限和可选费用硬上限。
6. 完善用户预警、回答级扣减说明和超级管理员调整入口。
7. 在不调用真实模型、不修改生产配置的前提下完成本地实现和验证。

## 2. 固定产品决策

### 2.1 角色不变

系统继续只有：

```text
user
admin
super_admin
```

角色决定“能做什么”，额度决定“还能调用多少模型”，两者必须独立：

| 能力 | 普通用户 | 管理员 | 超级管理员 |
| --- | --- | --- | --- |
| 查看自己的额度和用量 | 是 | 是 | 是 |
| 查看全站脱敏用量 | 否 | 是 | 是 |
| 修改用户额度 | 否 | 否 | 是 |
| 因角色自动获得无限额度 | 否 | 否 | 否 |

不得新增“测试用户”“演示用户”“会员”等角色。`quota_plans`是内部配置表，不是账号身份，
普通用户页面不显示套餐选择和购买入口。

### 2.2 默认额度

内部只保留一个可用默认计划：

```text
code: free
period: monthly
token_limit: 1,000,000
request_limit: 500
estimated_cost_limit_cny: null
```

超级管理员可以给指定账号设置Token和请求次数覆盖值。覆盖值只影响额度，不改变角色。

### 2.3 计量范围

- 回答级Token由`model_usage_records`实际usage聚合。
- 普通RAG和Agent用户主动调用计入用户额度。
- 自动记忆提取继续记录系统成本，但默认`quota_billable=false`，不扣用户额度。
- `not_applicable`表示没有调用模型，扣0 Token、0请求。
- `unknown`表示模型可能已经调用但未返回usage，按本次保守预留Token结算。
- Embedding和Reranker保持独立计量，阶段19不把它们混入聊天Token额度。

## 3. 当前实现问题

### 3.1 执行开关关闭

`Settings.quota_enforcement_enabled`和Compose默认都是`false`，RAG与Agent因此使用
`DisabledQuotaGate`。

### 3.2 默认10万存在两处

- `0024_user_quota`插入`free.token_limit=100000`。
- `QuotaApplicationService._period()`在找不到计划时回退`(100000, 500)`。

`0024`已经生产执行，禁止修改历史迁移。

### 3.3 固定预留可能低估

当前默认：

```text
RAG: 4,000 Token
Agent: 12,000 Token
```

RAG输入还包含系统提示词、最近消息、长期记忆和知识片段，实际usage可能超过4000。
调用后虽然会记录实际值，但预留不足可能让最后一次调用把周期使用量推过硬上限。

### 3.4 配置和数据模型尚未完全生效

- `DEFAULT_QUOTA_PLAN_CODE`已经存在，但Quota Service仍硬编码查找`free`。
- `quota_plans.period_type`存在，但当前周期计算固定为UTC自然月。
- `estimated_cost_limit_cny`存在，但reserve和settle尚未执行费用限制。
- 修改默认计划不会自动更新本月已经创建的`quota_periods`快照。
- 当前只有关闭或强制执行两种语义，没有只观察不拦截的shadow模式。

## 4. 模块边界

保持调用方向：

```text
RAG / Agent Application Service
-> QuotaGatePort
-> QuotaApplicationService
-> QuotaRepository
-> MySQL
```

新增边界：

```text
QuotaReservationEstimatorPort
-> RagQuotaEstimator / AgentQuotaEstimator

QuotaPolicyMode
-> off / shadow / enforce
```

规则：

- Router不得计算额度、读取额度表或判断角色。
- RAG/Agent只传递准备调用所需的结构化预算信息，不读取Quota Model。
- Quota Service不得导入RAG或Agent Repository。
- 超级管理员调整继续通过usage公开应用服务并写现有audit模块。
- MySQL是额度真相源；本阶段不增加Redis额度副本。
- 实际usage、估算预留和最终扣减必须是三个明确字段，不能互相冒充。

## 5. 数据迁移

新增迁移：

```text
0025_quota_policy_v2
down_revision = 0024_user_quota
```

升级要求：

1. 把`quota_plans.code=free`的`token_limit`从100000更新为1000000。
2. 只更新当前及未来仍使用默认计划、且没有`token_limit_override`的额度周期。
3. 保留`used_tokens`、`reserved_tokens`、`used_requests`和全部历史usage。
4. 不覆盖超级管理员已经设置的用户Token覆盖值。
5. 不创建、删除或修改用户角色。
6. 迁移可重复预检，升级和降级均有真实MySQL测试。

当前周期调整后的计算：

```text
new_limit = 1,000,000
used_tokens = 原值
reserved_tokens = 原值
remaining = max(0, new_limit - used_tokens - reserved_tokens)
```

降级时只把仍等于100万、没有用户覆盖且由本迁移调整的默认配置恢复为10万；如果迁移后
超级管理员又修改了用户额度，不得用降级覆盖人工修改。具体实现可以通过迁移审计标记或
精确条件完成，禁止按全表无条件更新。

## 6. 三级执行模式

用枚举替换单一布尔语义：

```env
QUOTA_POLICY_MODE=off
```

模式：

| 模式 | 创建周期 | 计算预留 | 写shadow事件 | 阻止调用 |
| --- | --- | --- | --- | --- |
| `off` | 是 | 否 | 否 | 否 |
| `shadow` | 是 | 是 | 是 | 否 |
| `enforce` | 是 | 是 | 是 | 是 |

兼容策略：

- 新配置存在时以`QUOTA_POLICY_MODE`为准。
- 迁移期允许旧`QUOTA_ENFORCEMENT_ENABLED=true`映射为`enforce`。
- 旧值为false且新配置缺失时映射为`off`。
- `.env.example`和Compose统一改用新配置，兼容读取保留一个发布周期。

shadow模式黑盒：

```text
用户发送问题
-> 计算本次应预留额度
-> 判断如果enforce是否会超限
-> 不阻止模型调用
-> 保存would_block=true/false和原因
-> 模型完成后照常记录实际usage
```

`off`必须保持阶段18兼容行为：只确保额度周期存在，不调用动态预留估算器，也不能因为
阶段19的单次预留上限拒绝原本合法的请求。`shadow`可以计算超过建议单次上限的估算值并
记录观察结果，但仍不得阻止模型；只有`enforce`可以因单次估算超过策略上限返回稳定错误。

shadow事件不得保存问题、Prompt、回答或知识正文，只保存用户ID、surface、预留值、周期
剩余值和稳定原因码。

建议原因码：

```text
TOKEN_LIMIT_EXCEEDED
REQUEST_LIMIT_EXCEEDED
COST_LIMIT_EXCEEDED
QUOTA_POLICY_UNAVAILABLE
```

## 7. 动态预留

### 7.1 RAG

RAG预留不得再固定为4000。估算输入包括：

```text
系统提示词预算
+ 当前问题估算
+ 最近历史实际字符/估算Token
+ MemoryContext实际预算
+ top_k * 单片段最大预算
+ 来源包装预算
+ 最大输出Token
+ 安全余量
```

第一版不调用外部Tokenizer API。通过`QuotaReservationEstimatorPort`提供可替换估算器：

```text
estimated_input_tokens
estimated_output_tokens
safety_margin_tokens
requested_tokens
estimation_method
```

字符规则只用于调用前保守预留，页面必须标记为estimate；回答完成后的实际Token仍只来自
模型usage，禁止把字符估算写成actual。

建议边界：

```text
RAG最小预留：4,000
RAG最大预留：20,000
安全余量：20%
```

如果保守估算超过单次最大预留，`enforce`在调用前返回稳定的“上下文过长”错误，不继续
请求模型；`shadow`保留未截断估算用于观察并继续调用，`off`完全跳过本次额度估算。

### 7.2 Agent

Agent已有`agent_max_tokens=12000`硬预算，默认预留仍以该策略上限为主。估算器可以根据
当前任务和工具上限降低预留，但不得超过Agent策略预算，也不得低于模型一次最大输出和
固定最小输入预算之和。

### 7.3 结算

```text
reserve(requested_tokens)
-> 模型调用
-> actual：按usage.total_tokens结算，退回多余预留
-> unknown：按全部预留结算
-> not_applicable：释放预留，扣0
-> 失败但已有usage：按已知usage结算
-> 确认模型未调用：释放预留
```

如果实际Token大于预留：

- 必须完整记录实际usage。
- 最终周期允许显示本次产生的明确超额，但下一请求必须阻止。
- 记录`RESERVATION_UNDERESTIMATED`事件，供管理员观察估算器。
- 不能截断或伪造实际Token使账本看起来未超额。

## 8. Token与费用双限制

Token额度始终启用；费用额度为可选第二道闸门：

```text
token_limit = 1,000,000
estimated_cost_limit_cny = null  # 第一版默认不限制费用
```

只有以下条件全部满足时才执行费用硬限制：

1. 计划或用户覆盖值配置了费用上限。
2. 当前模型输入/输出价格已配置。
3. 本次预留费用可以可靠估算。

费用未知时不能显示为0。enforce模式下若用户配置了费用硬上限但价格不可用，应返回
`QUOTA_POLICY_UNAVAILABLE`并且不调用模型，避免成本保护失效。

本阶段先完成数据流和测试，不给默认计划强行设置人民币上限。以后增加多模型选择时，再
根据模型价格决定默认费用策略或加权积分，不在阶段19引入“会员套餐”。

## 9. 用户和管理员界面

### 9.1 普通用户

个人中心保持一个额度页面：

```text
本月额度：1,000,000
已使用
已预留
剩余
重置时间
请求次数
```

预警：

- 低于80%：正常。
- 达到80%：普通提醒。
- 达到95%：明显警告。
- 达到100%且enforce：输入区保留内容，发送前显示额度不足和重置时间。

每条助手消息底部：

```text
实际：输入 3,620 · 输出 766
本次额度扣减：4,386
```

如果实际usage未知：

```text
实际Token：模型未返回
额度扣减：按预留8,000结算
```

“预计还能问多少次”只根据当前用户最近有效回答的平均扣减量估算，并明确标注“约”；
样本不足时不显示，不能用固定数字误导。

### 9.2 管理员

管理员继续只能查看：

- 全站Token、费用、请求和覆盖率。
- 高消耗、额度耗尽、unknown和预留低估用户。
- shadow模式下的`would_block`次数。

管理员不能调整额度。

### 9.3 超级管理员

超级管理员调整对话框只保留：

```text
Token上限覆盖值
请求上限覆盖值
可选费用上限覆盖值
调整原因
```

删除“计划”“套餐”和角色选择。保存后写审计，但不改用户角色。清空覆盖值表示恢复
100万默认值。

## 10. API与错误契约

复用阶段18接口，不新增平行额度API：

```text
GET /api/v1/profile/quota
GET /api/v1/profile/usage/*
GET /api/v1/admin/usage/*
PUT /api/v1/admin/users/{id}/quota
```

建议在额度响应兼容增加：

```text
policy_mode
warning_level: normal/warning/critical/exhausted
charged_tokens
estimated_remaining_requests nullable
```

错误：

| 状态 | code | 含义 |
| --- | --- | --- |
| 429 | `QUOTA_EXCEEDED` | Token、请求或费用硬额度不足 |
| 503 | `QUOTA_POLICY_UNAVAILABLE` | enforce模式下无法可靠执行额度策略 |
| 409 | `QUOTA_RESERVATION_CONFLICT` | 幂等reservation状态冲突 |

原有SSE `token/source/done/error`语义不改变。额度不足发生在模型调用前，应通过现有稳定
错误入口返回，Qwen/Embedding/Reranker调用次数必须为0。

## 11. 分步开发

### 任务19.1：策略契约与0025迁移

- 增加`QuotaPolicyMode`和兼容配置解析。
- 新增`0025_quota_policy_v2`。
- 默认计划和符合条件的当前周期提高到100万。
- 覆盖升级、降级、已有使用量和用户覆盖保护。
- 不改RAG/Agent、不改前端、不调用模型。

### 任务19.2：shadow模式

- 增加只观察不阻断的策略结果和脱敏事件。
- off保持阶段18现状，enforce保持现有硬拦截语义。
- 覆盖Token、请求、策略不可用和重复请求。

### 任务19.3：动态预留估算器

- 建立`QuotaReservationEstimatorPort`及RAG/Agent实现。
- RAG根据真实上下文预算和top_k保守估算。
- Agent遵守现有12000 Token策略上限。
- 覆盖短问、长历史、多片段、长期记忆和预留低估。

### 任务19.4：结算与可选费用闸门

- 完善actual/unknown/not_applicable/失败/停止/断线结算。
- 启用配置存在时的费用预留和硬限制。
- 增加预留低估与过期reservation对账指标。

### 任务19.5：用户界面

- 默认100万、80%/95%预警、回答实际/扣减双显示。
- 增加重置时间和样本足够时的剩余问答估算。
- 保持桌面、移动端、刷新历史和SSE一致。

### 任务19.6：三角色管理界面

- 管理员只读，超级管理员可调整。
- 删除计划输入，不新增身份。
- 调整值和原因写审计，角色保持不变。

### 任务19.7：完整本地验收与发布准备

- 完整后端、前端、SSE、构建和Alembic检查。
- 真实本地MySQL并发、迁移往返和reservation恢复。
- 1440、1280、390浏览器验收。
- 敏感信息、文档链接和`git diff --check`。
- 更新handoff，只留下生产发布与shadow启用预检。
- 不SSH、不部署、不修改生产开关、不调用真实模型。

## 12. 验收矩阵

必须证明：

- 新用户和无覆盖旧用户月额度为100万。
- 已使用Token不因迁移归零或减少。
- 超级管理员已有覆盖值不被迁移覆盖。
- 系统仍只有`user/admin/super_admin`三种角色。
- off不阻断，shadow只记录，enforce真正阻断。
- enforce额度不足时模型调用为0。
- 两个并发请求不能共同穿透只够一次的额度。
- RAG长上下文不再始终只预留4000。
- actual退差额、unknown扣预留、not_applicable扣0。
- 管理员不能调额度，超级管理员调整写审计。
- 页面刷新后回答Token、扣减和剩余额度一致。
- 记忆提取仍不扣用户额度。
- 认证、RAG、Agent、资料审核、记忆和阶段18统计不回归。

## 13. 停止条件

出现以下情况立即停止当前小任务并记录handoff：

- 迁移会覆盖用户手工额度或清空历史使用量。
- shadow模式意外阻止模型调用。
- enforce超限后仍调用模型。
- 预留/结算可能重复扣减。
- 角色和额度修改发生耦合。
- unknown被伪装成actual或0。
- 日志/API出现Prompt、回答、医学正文或秘密。
- 无法在不覆盖既有`auth/service.py`修改的情况下继续。

## 14. 新开发窗口读取范围

阶段19开发窗口只需：

1. 完整阅读`AGENTS.md`和`docs/handoff.md`。
2. 完整阅读本文。
3. 定向读取阶段18的Quota、Usage、RAG/Agent接入、前端用量页和对应测试。
4. 不全文读取历史阶段、RAG评估JSON或旧发布审计。

每完成一个任务，运行对应测试、更新handoff并自动进入下一任务。任务19.7完成前不得把
阶段19标记为完成；本地完成不等于生产已经启用。
