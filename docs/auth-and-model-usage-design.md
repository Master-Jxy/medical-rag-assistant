# 邮箱账号生命周期与模型用量计量设计

> 最后更新：2026-07-29
> 状态：`[本地代码与无费用验证完成，生产安全闸门待执行]`
> 当前唯一开发入口：`docs/handoff.md`

本文定义阶段16的实现边界。目标是补齐邮箱验证码注册、忘记密码、旧测试账号安全清理，
并让普通RAG和Agent在供应商返回可靠计量时显示真实输入/输出Token与估算费用。

本阶段不得顺手修改RAG检索策略、Prompt、知识审核规则、Agent工具、SSE正文协议或部署
拓扑。SMTP授权码、API Key、JWT密钥和生产数据不得写入本文、源码、Git或日志。

## 1. 现状与问题

### 1.1 认证现状

- `users.email`已经是必填、唯一的登录账号。
- 注册接口当前收到邮箱和密码后直接创建用户，没有证明用户拥有该邮箱。
- 系统只有短期Bearer JWT，没有忘记密码和服务端主动失效旧Token的机制。
- 现有账号均为无价值测试账号，但会话、Agent、资料和审核数据通过外键关联用户，
  不能直接执行无条件`DELETE FROM users`。

### 1.2 Token和费用现状

当前普通RAG链路是：

```text
DashScope流式响应
-> DashScopeAsyncChatModel只向上返回content字符串
-> 最终响应中的usage被丢弃
-> RagService固定写token_measurement=unknown
-> Telemetry只能显示Token未知、费用未知
```

因此“未知”是后端计量信息没有穿透，不是前端格式错误。阶段16必须从模型适配器开始修复，
不能在Vue中用字数猜Token。

## 2. 固定产品决策

1. 注册账号继续使用邮箱、密码和昵称，但必须先取得邮箱验证码。
2. 忘记密码使用邮箱验证码重置，不发送明文密码或可长期复用的重置链接；成功消费
   验证码也会把迁移前旧账号标记为邮箱已验证，不自动信任未经过验证码的旧邮箱。
3. 邮箱验证码依赖Redis和SMTP；任一不可用时安全失败，不降级成本机内存验证码。
4. 密码重置后，重置前签发的所有JWT立即失效。
5. 旧测试账号通过独立维护命令清理，不把生产数据删除写入Alembic迁移。
6. 保留一个真实邮箱的超级管理员，公共知识资产归属在清理前转移给该账号。
7. 模型返回usage时保存实际输入/输出Token；没有返回时继续明确显示未知。
8. 费用是按调用当时配置的单价计算的估算值，不宣称等于供应商最终账单。
9. 确定性回答没有调用模型时显示“未调用模型、0 Token、¥0”，不显示未知。
10. 聊天模型、Embedding和Reranker分别计量；本阶段不把不同计费单位混成一个数字。

## 3. 模块边界

后端调用方向保持：

```text
Auth Router
-> Auth Application Service
-> User Repository / Verification Store Port / Email Sender Port
-> MySQL / Redis Adapter / QQ SMTP Adapter

RAG或Agent Service
-> Chat Model Port
-> DashScope Chat Model Adapter
-> usage结果
-> Model Usage Recorder Port
-> MySQL Usage Repository + Telemetry聚合
```

约束：

- Router只负责参数、身份依赖和响应，不直接操作SMTP、Redis或SQL。
- 验证码生成、验证、原子消费和频率控制属于`EmailVerificationService`。
- `EmailSenderPort`只描述发送能力；QQ SMTP细节放在Infrastructure Adapter。
- 密码修改和`token_version`递增必须在同一MySQL事务中完成。
- 模型Port返回厂商无关的正文块和用量对象，不向业务层暴露DashScope响应对象。
- 用量记录失败不得破坏已经生成的回答，但必须记录脱敏错误并把该次计量标为未知。
- 管理统计只能读取脱敏账本和聚合结果，不读取Prompt、问题、回答或知识正文。

建议新增或扩展：

```text
backend/app/modules/auth/
|-- email_verification.py
|-- ports.py
`-- maintenance.py

backend/app/infrastructure/
|-- qq_smtp_email_sender.py
|-- redis_email_verification_store.py
`-- async_chat_model.py

backend/app/modules/usage/
|-- models.py
|-- schemas.py
|-- repository.py
|-- service.py
`-- ports.py
```

具体文件名可以服从当前仓库模式，但模块所有权和依赖方向不能改变。

## 4. 数据设计

### 4.1 迁移0020：邮箱账号生命周期

建议迁移名：

```text
0020_email_account_lifecycle
```

为`users`增加：

| 字段 | 类型 | 规则 | 用途 |
| --- | --- | --- | --- |
| `email_verified_at` | datetime nullable | 新验证账号写UTC时间 | 证明邮箱已验证 |
| `token_version` | int non-null | 默认0 | 使旧JWT失效 |

不把`email`改为可空。迁移只增加结构，不删除、重命名或自动验证旧账号。

### 4.2 迁移0021：模型用量账本

建议迁移名：

```text
0021_model_usage_records
```

建议字段：

| 字段 | 规则 |
| --- | --- |
| `id` | 主键 |
| `call_id` | 唯一幂等标识 |
| `request_id` | 可空请求标识 |
| `user_id` | 可空，用户删除时按设计置空或随业务清理 |
| `surface` | `rag`、`agent`等调用入口 |
| `operation` | `answer`、`plan`、`tool_summary`等公开用途 |
| `model_name` | 实际模型名 |
| `input_tokens` | 可空 |
| `output_tokens` | 可空 |
| `total_tokens` | 可空 |
| `token_measurement` | `actual`、`unknown`、`not_applicable` |
| `input_price_snapshot` | 可空，每百万Token人民币单价快照 |
| `output_price_snapshot` | 可空，每百万Token人民币单价快照 |
| `estimated_cost_cny` | 可空 |
| `created_at` | UTC时间 |

账本禁止保存Prompt、用户问题、模型回答、文档正文、验证码、邮箱、JWT或API Key。
`call_id`保证SSE收尾或网络重放不会重复记账。

## 5. 邮箱验证码注册

### 5.1 接口

```text
POST /api/v1/auth/email-verification/request
POST /api/v1/auth/register
```

请求验证码建议字段：

```json
{
  "email": "user@example.com",
  "purpose": "register"
}
```

注册请求在原字段上增加：

```json
{
  "email": "user@example.com",
  "password": "user-password",
  "display_name": "用户昵称",
  "verification_code": "123456"
}
```

### 5.2 黑盒流程

```text
用户填写邮箱
-> 前端请求发送验证码
-> Auth Service校验格式和发送频率
-> 生成安全随机6位验证码
-> Redis只保存验证码HMAC、失败次数和10分钟TTL
-> EmailSenderPort调用QQ SMTP发送
-> 用户提交邮箱、验证码、密码和昵称
-> Service原子校验并消费验证码
-> MySQL创建email_verified_at非空的用户
-> 返回现有登录响应或要求用户登录
```

验证码不得明文写入数据库、Redis、日志或响应。密码不得暂存在Redis。

### 5.3 安全策略

- 验证码默认10分钟过期。
- 同一邮箱默认60秒内不能重复发送。
- 同一验证码最多5次失败；超过后作废。
- 验证成功必须原子消费，不能重复注册。
- Redis键只使用邮箱规范化后的HMAC或稳定摘要，不出现明文邮箱。
- 发送和验证接口同时按用户/IP限流，不能只依赖前端倒计时。
- 注册邮箱已存在、邮件发送失败等响应不得泄露可用于批量枚举的内部细节。
- SMTP或Redis不可用时返回稳定错误码和`request_id`，不创建未验证账号。

## 6. 忘记密码与JWT失效

### 6.1 接口

```text
POST /api/v1/auth/password-reset/request
POST /api/v1/auth/password-reset/confirm
```

重置请求无论邮箱是否存在，都返回相同的公开提示：

```text
如果该邮箱已注册，验证码将发送到邮箱。
```

确认请求：

```json
{
  "email": "user@example.com",
  "verification_code": "123456",
  "new_password": "new-password"
}
```

### 6.2 黑盒流程

```text
用户输入邮箱
-> 后端统一响应，存在账号时才发送验证码
-> 用户提交邮箱、验证码和新密码
-> 原子消费password_reset用途验证码
-> 同一事务更新密码哈希并令token_version + 1
-> 旧JWT中的ver与数据库不一致
-> 后续任意受保护接口返回401
-> 用户使用新密码重新登录
```

新JWT增加`ver`声明。每次鉴权除校验签名、过期时间和用户状态外，还要比较数据库中的
`token_version`。角色仍以数据库为真相源，不写进可长期信任的前端状态。

## 7. QQ SMTP与配置

仅在本地或服务器真实`.env`中填写：

```env
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USERNAME=example@qq.com
SMTP_PASSWORD=replace_with_qq_smtp_authorization_code
SMTP_USE_SSL=true
SMTP_TIMEOUT_SECONDS=10
MAIL_FROM_NAME=医疗知识库助手
EMAIL_CODE_TTL_SECONDS=600
EMAIL_CODE_RESEND_SECONDS=60
EMAIL_CODE_MAX_ATTEMPTS=5
```

端口465使用SSL，不能同时再打开STARTTLS。`SMTP_PASSWORD`是QQ邮箱SMTP授权码，不是
QQ密码。示例文件只能保留占位符。

邮件发送必须设置超时，失败不自动无限重试。第一版不引入Celery或消息队列；同步发送
若影响接口体验，再在后续独立任务中引入受控后台任务，不能先增加新的基础设施复杂度。

## 8. 旧测试账号清理

### 8.1 原则

账号清理是一次生产维护操作，不是数据库迁移。当前外键中同时存在`RESTRICT`、
`CASCADE`和`SET NULL`，直接删用户可能失败，也可能误删关联业务数据。

建议维护入口：

```powershell
python -m scripts.reset_demo_accounts --owner-email <真实邮箱> --preflight
python -m scripts.reset_demo_accounts --owner-email <真实邮箱> --confirm
```

脚本必须从`backend`目录以模块方式运行。

### 8.2 执行顺序

```text
只读预检所有用户和关联数量
-> 输出保留账号、待转移公共资产、待删除个人数据
-> 完整备份MySQL、上传文件、Chroma和Redis
-> 把保留超级管理员更新为真实邮箱并标记已验证
-> 把必须保留的公共文档/提交归属转移给保留账号
-> 删除其他测试账号的个人会话、消息、Agent数据、记忆和反馈
-> 删除对应临时Redis键
-> 删除测试用户
-> 重查外键、账号数、公共文档数、Chroma片段数和上传文件数
```

脚本要求：

- `--preflight`绝不写数据。
- `--confirm`还需要固定确认短语，不能把普通命令误当删除授权。
- 预检与执行数量不一致、发现未知外键或公共资产无法确定归属时立即停止。
- 不删除公共知识正文、上传文件或Chroma向量。
- 不把本次“同意写设计文档”视为未来生产删除授权；执行时必须再次确认。

## 9. Token与费用计量

### 9.1 厂商无关类型

建议在模型Port增加：

```text
ModelUsage
|-- input_tokens: int | None
|-- output_tokens: int | None
|-- total_tokens: int | None
`-- measurement: actual | unknown | not_applicable

GeneratedAnswerChunk
|-- content: str
`-- usage: ModelUsage | None
```

流式过程中大多数chunk只有`content`；最终chunk或流结束结果携带`usage`。DashScope
适配器优先读取`input_tokens/output_tokens`，并兼容
`prompt_tokens/completion_tokens`字段名。

### 9.2 普通RAG黑盒流程

```text
RagService发起一次流式回答
-> DashScope Adapter逐块返回content
-> SSE继续按原token事件输出文字
-> 最终响应解析usage
-> RagService把完整回答和ModelUsage交给记录服务
-> 账本按call_id幂等写入
-> Telemetry聚合已知Token、费用和覆盖率
-> 管理页面展示本次及累计计量
```

正文SSE协议保持不变；usage可放入最终`done`事件的兼容新增字段，或者只进入后台统计，
具体选择在16.2a冻结API契约后实现。

### 9.3 费用计算

新增配置：

```env
CHAT_INPUT_PRICE_PER_MILLION_TOKENS_CNY=
CHAT_OUTPUT_PRICE_PER_MILLION_TOKENS_CNY=
```

公式：

```text
估算费用 =
输入Token × 输入单价 / 1,000,000
+ 输出Token × 输出单价 / 1,000,000
```

单价按调用时快照入账，后续改价不重算历史记录。只有Token和对应单价都可靠时才给出费用；
否则费用保持未知。不得用“字符数/2”等经验公式冒充实际Token。

### 9.4 显示语义

| 情况 | Token显示 | 费用显示 |
| --- | --- | --- |
| 厂商返回usage且单价已配置 | 实际输入/输出 | 估算人民币费用 |
| 厂商返回usage但未配置单价 | 实际输入/输出 | 未配置 |
| 厂商未返回usage | 未知 | 未知 |
| 确定性回答，未调用模型 | 0 / 0，并标注未调用模型 | ¥0 |
| Embedding或Reranker调用 | 独立指标 | 不混入聊天输入/输出 |

管理员统计增加：

```text
known_model_calls
unknown_model_calls
measurement_coverage
```

某一次缺少usage只降低覆盖率，不能让所有已知累计值一起变成未知。

## 10. 前端交互

### 10.1 注册页

- 邮箱、验证码、发送按钮、密码、确认密码、昵称。
- 发送成功后显示60秒倒计时；倒计时仅改善体验，后端仍独立限流。
- 错误区显示稳定提示和`request_id`。
- 注册成功后进入登录页或沿用冻结后的注册响应，不在页面保存验证码。

### 10.2 忘记密码

- 登录页增加“忘记密码”入口。
- 重置页分为邮箱、验证码、新密码、确认密码。
- 请求验证码后始终使用统一提示，不能暴露邮箱是否注册。
- 重置成功后清理本地Token和当前用户，回到登录页。

### 10.3 运行统计

- 输入Token、输出Token分开显示。
- 费用明确标注“估算”，并显示计量覆盖率。
- `unknown`使用“模型未返回计量”，未配置单价使用“Token已知，单价未配置”。
- 确定性回答显示“未调用模型”，不能与适配器故障混为一类。

## 11. 分步开发路线

### 16.1a 邮箱字段、配置、Port和Fake适配器 `[已完成]`

- 新增迁移0020，但不清理账号。
- 增加SMTP和验证码配置校验。
- 建立`EmailSenderPort`、验证码Store Port和Fake实现。
- 增加配置、迁移、Port和架构边界测试。
- 不发送真实邮件，不改注册接口。

### 16.1b 注册验证码后端 `[已完成]`

- 实现Redis验证码存储、QQ SMTP适配器和发送接口。
- 注册接口要求原子消费验证码。
- 覆盖过期、重放、错误次数、并发、限流、SMTP/Redis故障和邮箱枚举测试。
- 默认Fake SMTP验收；真实QQ邮件发送需单独确认。

### 16.1c 忘记密码和JWT token_version `[已完成]`

- 实现请求/确认接口。
- JWT增加`ver`并在鉴权时与数据库比较。
- 覆盖旧JWT失效、并发重置、停用账号和统一响应。

### 16.1d 前端认证生命周期 `[已完成]`

- 增加验证码注册和忘记密码页面。
- 保持现有登录、401清理、受保护路由和角色菜单不回归。
- 完成桌面和390宽移动端浏览器验收。

### 16.1e 测试账号清理命令 `[代码与无费用预检已完成，生产未执行]`

- 先实现无副作用`--preflight`和Fake/临时库测试。
- 生产执行前重新备份、展示精确清单并取得用户当次授权。
- 清理后验证保留超级管理员、公共知识、Chroma和文件基线。

### 16.2a 普通RAG实际usage穿透 `[已完成]`

- 升级聊天模型Port和DashScope适配器。
- 保持流式正文和停止生成行为不变。
- 使用固定Fake响应覆盖实际、未知、零调用和取消场景。

### 16.2b MySQL计量账本与管理员聚合 `[已完成]`

- 新增迁移0021和幂等记录服务。
- 管理统计增加输入/输出、估算费用、已知/未知调用和覆盖率。
- 进程内Telemetry仍可用于实时健康，MySQL账本负责重启后保留用量。

### 16.2c Agent计量语义统一 `[已完成]`

- 统一规划、工具后总结和最终生成的用量累计。
- 移除用户可见的字符数估算语义；无法取得usage时标为未知。
- 0工具确定性回答保持0 Token、¥0。

### 16.3 完整验证、清理与发布 `[本地无费用验证完成，生产待独立授权]`

- L2完整后端、前端、SSE、迁移和敏感信息检查已完成。
- 生产发布前完成四类数据备份和回滚演练。
- 测试账号清理、真实SMTP、真实模型计量分别取得授权，不能共用一次确认。
- 部署后验证登录、重置、旧JWT失效、RAG流式、Agent、管理统计和公共知识基线。

## 12. 停止条件与回滚

出现以下任一情况立即停止当前小步：

- 迁移无法在旧数据上升级或降级。
- SMTP授权码、验证码、邮箱、Prompt或正文进入日志/Git。
- Redis故障时仍创建未验证用户。
- 密码重置后旧JWT仍可访问。
- usage缺失时被伪造成实际Token或费用。
- 测试账号清理预检数量与执行时不同。
- 公共文档、上传文件或Chroma片段数量意外变化。

回滚顺序：

```text
关闭新接口入口或功能开关
-> 回退应用版本
-> 必要时降级0021和0020
-> 账号清理若已执行则从备份恢复MySQL/文件/Chroma/Redis
-> 重查认证、公共知识和RAG/Agent主链路
```

## 13. 新开发窗口读取范围

阶段16的新开发窗口只需：

1. 完整阅读`AGENTS.md`和`docs/handoff.md`。
2. 阅读本文对应当前小步的章节。
3. 定向读取`docs/development-roadmap.md`阶段16。
4. 只读当前小步涉及的认证、模型Port、Telemetry或前端源码与测试。

不要全文回放历史评估报告、发布审计和Agent设计。唯一下一任务由`docs/handoff.md`维护。
