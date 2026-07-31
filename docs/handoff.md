# 当前开发交接

> 最后更新：2026-07-31
> 本文件只保留当前事实、工作区边界和一个下一任务。

## 1. 当前真实状态

阶段17和阶段18已完成全部代码、迁移、页面、本地验证和生产发布。生产源码为
`a1a38531ef067f9e7791f1982a7fe6b3b372312f`，数据库为`0024_user_quota (head)`，
四容器healthy；**自动记忆提取和额度执行两个生产开关仍保持关闭**。

阶段19的19.1～19.7及生产发布预检修复已完成代码、`0025_quota_policy_v2`、前后端页面
和全部本地无费用验收；**尚未提交、推送或部署，生产仍是上述阶段18版本和0024**。
本地默认额度为100万Token/500请求，策略默认off；当前已经具备先以off发布的条件。

阶段17：

- 17.1：`0022_memory_v2`、记忆Port/Repository/兼容迁移和无副作用上下文读取完成。
- 17.2：幂等提取、固定Schema、敏感过滤、去重、冲突候选、有限重试和过期任务恢复完成。
- 17.3：候选确认/拒绝、来源、修订、关闭保留/确认清空和个人中心完成。
- 17.4：本地相关Top-K与字符预算完成；普通RAG统一使用`MemoryContextProvider`。
- 17.5：Agent复用同一Provider；RAG/Agent回答完成后持久化调度，SSE后台快速恢复完成；
  调度/提取失败不改变已完成回答。
- 17.6：敏感健康背景必须确认，来源归属、用户隔离、重复事件、进程中断、Fake提取usage、
  完整L2、迁移和三宽浏览器验收通过。

阶段18：

- 18.1：`ModelUsage`迁入usage模块，RAG Port保留兼容导出；`0023_usage_groups`完成。
- 18.2：RAG/Agent SSE和刷新历史返回回答级usage，前端区分actual、unknown、
  not_applicable和未定价。
- 18.3：个人汇总、趋势、surface/model分布、明细和额度页面完成。
- 18.4：`0024_user_quota`、计划/分配/周期/reservation、用户行与周期行锁、幂等结算、
  unknown保守结算、not_applicable零扣减和过期reservation对账完成。
- 18.5：RAG/Agent统一Quota Gate完成；额度不足时Fake模型/Planner为0次，停止、失败、
  客户端断开和重复请求结算有测试。
- 18.6：管理员总览、趋势、筛选、高消耗/异常用户、超级管理员额度调整和审计完成；
  普通管理员调整返回403。
- 18.7：完整自动化、真实本地MySQL并发与迁移往返、敏感扫描、链接、差异和
  1440/1280/390本地浏览器验收完成；生产备份、迁移、容器和无费用黑盒验收完成。

## 2. 数据库迁移

- `0022_memory_v2`
- `0023_usage_groups`
- `0024_user_quota`（当前生产head）
- `0025_quota_policy_v2`（当前代码与本地MySQL唯一head，尚未生产执行）

本地MySQL最终验证：

```text
0024 -> 0025
0025 -> 0024
0024 -> 0025
```

阶段19最终往返专门处理了本地数据库已经标记为早期未发布0025、但缺少后续新增列的
状态：先安全降到0024，再升级最新0025。往返前后保持6个用户、2个会话、22条消息、
1个额度周期和0条reservation；free计划为100万/500、费用上限为空，当前周期使用量
没有减少。双线程争抢只够一次的额度时为1次reserved、1次rejected；过期reservation
无账本时正确release。本次并发和浏览器临时账号均已精确清理，最终仍为6个本地用户。

生产从`0021`升级时发现一条历史`call_id`超过36字符，首次`0023`回填触发MySQL 1406；
MySQL非事务DDL已添加列和索引、Alembic停在`0022`。修复提交`a1a3853`改用确定性UUID
回填并支持部分DDL恢复，新增回归后从该半状态安全完成`0023`、`0024`。迁移前后均为
13个用户、7个会话、126条消息、27份文档和8条usage；没有恢复备份或删除业务数据。

## 3. 验证证据

```text
backend\.venv\Scripts\python.exe -m pytest -q backend/tests
446 passed

D:\Nodejs\npm.cmd --prefix frontend test
16 files / 59 tests passed

D:\Nodejs\npm.cmd --prefix frontend run test:stream
SSE parser test passed

D:\Nodejs\npm.cmd --prefix frontend run build
Vite production build passed
```

其他检查：

- 阶段17/18记忆、额度与集成专项测试：17 passed，直接覆盖来源归属、内容去重、冲突
  修订、not_applicable零扣减以及失败流unknown保守结算。
- 阶段19最终额度/迁移专项40项通过；off/shadow/enforce、动态预留、actual/unknown/
  not_applicable、低估、费用策略、并发、停止/失败/断线、三角色和审计均由Fake覆盖。
- 发布预检发现动态RAG估算发生在Gate前，使off及shadow在合法极限上下文下可能被
  `QUOTA_RESERVATION_TOO_LARGE`阻断。修复后off完全跳过RAG/Agent估算，shadow保留未
  截断估算并继续，只有enforce拒绝；新增3项集成回归，专项31项、完整后端446项通过。
- Alembic代码与本地MySQL单一head：`0025_quota_policy_v2`；生产仍为0024。
- `git diff --check`通过，仅有Windows LF/CRLF提示。
- 敏感扫描没有真实密钥模式，Git没有跟踪`.env`，浏览器临时密码未写入工作区。
- 文档相对链接目标全部存在。
- `backend/app/modules/auth/service.py`保持任务开始前SHA-256
  `9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0`。
- 阶段19浏览器实际`window.innerWidth`为1440、1280、390：普通用户正确显示100万、
  95%预警、50,000剩余和20/500请求；管理员调整按钮数量为0并显示预警/would-block/
  低估观察；超级管理员可打开不含计划/套餐的四字段调整框。三页均无页面级横向溢出，
  宽表只在局部容器滚动，390宽对话框完整位于视口内，浏览器控制台无应用错误。
- 浏览器验收先发现非reload旧后端导致新字段不完整，重启本地后端后通过；又发现管理员
  95%用户行误显示正常，修复状态映射并增加组件断言后复验通过。
- 生产完整备份`/home/deploy/medical-rag-backups/backup-20260731T004301Z`全部SHA-256
  校验通过；旧backend/web镜像和旧前端目录已保留。
- 生产HTTPS首页、登录、个人中心、管理员用量路由为200，HTTP为308；新旧受保护API
  未登录均为401。静态包哈希与本地正式构建一致。
- 生产保持27份文档、103个Chroma片段、27个上传文件；8条历史usage分组ID均为36位，
  默认额度计划1条，周期、reservation和提取任务均为0。
- 线上自动可视浏览器控制在加载公网IP时超时；本机HTTPS与服务器静态/DOM资源正常，
  因此没有把线上1440/1280/390自动点击验收写成通过。

## 4. 工作区与安全边界

- 工作区保留开始前未提交修改；未回退、覆盖或格式化受保护的auth Service。
- 当前窗口新增/更新阶段19设计文档、路线图和交接入口；开发窗口应在这些修改之上继续，
  不得把它们当作无关脏文件回退。
- 本地浏览器验收新增`phase18-ui-user@example.com`和
  `phase18-ui-super@example.com`测试账号；没有删除任何既有账号或业务数据。
- 发布提交和迁移恢复提交已推送到GitHub并同步生产；服务器仓库工作树干净。首次
  ff-only因历史root所有权留下的半成品工作树已保存为服务器stash后重新安全快进。
- 没有调用真实Qwen、Embedding、Reranker、SMTP，没有创建、删除或修改生产账号。
- 阶段19只创建并随后精确删除了本地并发/浏览器验收账号；原有6个本地账号和业务数据
  保持。没有读取桌面授权码或其他真实凭据。
- `MEMORY_AUTO_EXTRACTION_ENABLED=false`和`QUOTA_ENFORCEMENT_ENABLED=false`已在
  生产运行时实测。
- 真实提取模型usage、真实额度拦截和真实RAG/Agent计量仍未验收，不能把“代码与表结构
  已上线”写成“两个开关已经启用”。

阶段19已经完成本地开发和无费用验收：默认额度计划提高到100万Token/月，保持500次
请求；增加off/shadow/enforce、RAG动态预留、可选费用闸门和三角色额度管理。系统角色
仍只有`user/admin/super_admin`，额度策略不创造新身份。完整设计见
`docs/quota-policy-v2-design.md`；生产尚未发布或启用。

阶段19开发进度：

- 19.1已完成：新增`QuotaPolicyMode`及新配置优先、旧布尔兼容解析；新增
  `0025_quota_policy_v2`，默认100万Token/500请求，符合条件的当前周期安全更新；
  历史使用量、reservation和人工覆盖受保护，迁移支持重复升级和精确降级。
- 19.1验证：额度/迁移专项19项、完整后端429项通过；真实本地MySQL完成
  `0024→0025→0024→0025`，6个本地用户、已有周期和reservation计数保持，最终head为
  `0025_quota_policy_v2`。应用账号无建库权限的临时库预检在创建前返回1044，随后使用
  现有本地库受控往返，没有读取root凭据。
- 19.2已完成：off只创建周期、不预留不阻断；shadow计算并保存脱敏would-block事件后
  继续调用；enforce在调用前阻断。事件只保存用户、surface、模式、预留数、剩余额度和
  稳定原因码；幂等重复不新增事件或reservation。
- 19.2验证：额度/RAG/维护命令专项31项通过；首次完整回归发现演示账号维护命令未登记
  新用户外键，补充事件计数和显式删除后，完整后端434项通过。
- 19.3已完成：新增厂商无关`QuotaReservationEstimatorPort`及结构化估算结果。RAG按
  系统Prompt、问题、已按现有预算截断的历史与相关记忆、`top_k`片段上限、来源包装、
  最大输出和20%余量动态预留，enforce建议范围4000～20000；估算超过上限时只有
  enforce在Fake模型前返回`QUOTA_RESERVATION_TOO_LARGE`，shadow继续观察，off跳过估算。
  Agent先构建本地上下文再预留，可降低请求值但始终
  不超过现有12000策略上限；字符估算没有写入actual usage。
- 19.3验证：估算器、RAG/Agent共享链路专项30项通过；完整后端437项通过。覆盖短问最小
  值、长历史、多片段、记忆预算、Agent上下限、超长上下文Fake模型0次，以及unknown按
  本次动态reservation结算。
- 19.4已完成：reservation保存输入/输出预留、价格快照、预留费用和最终扣减费用；actual
  按供应商usage全额结算，unknown按预留、not_applicable为0。实际Token高于预留时不截断，
  允许本次真实超额并记录`RESERVATION_UNDERESTIMATED`；下一请求由余额检查阻断。费用
  上限作为计划/用户/周期可空快照加入`0025`，默认仍为空；配置上限但缺可靠价格时
  enforce返回`QUOTA_POLICY_UNAVAILABLE`，shadow只记录继续。自动记忆等
  `quota_billable=false`记录不参与回答reservation对账。
- 19.4验证：结算、费用策略、迁移专项39项通过；完整后端442项通过。覆盖actual超预留、
  unknown、not_applicable、失败、停止、断线、费用超限、价格不可用、shadow继续、过期
  reservation恢复和低估指标，全部使用Fake usage/SQLite。
- 19.5已完成：个人额度页展示100万Token默认额度、Token与请求的已用/预留/剩余、重置
  时间和执行模式；按已用加预留计算normal、80% warning、95% critical和exhausted。
  最近至少3个有效回答时才按平均扣减量展示“约还能问多少次”。RAG/Agent SSE及刷新
  历史的回答级usage新增`charged_tokens`，页面明确区分供应商actual与额度扣减；
  unknown显示实际未知及保守扣减，not_applicable两者均为0。用户汇总排除
  `quota_billable=false`系统成本，管理员总览仍可观察系统成本。
- 19.5验证：回答级契约、额度页和RAG/Agent入口专项37项通过；完整后端443项、完整前端
  15文件57项通过。新增额度页组件测试覆盖100万展示、95%预警、请求余额、样本估算和
  unknown实际/扣减双口径。
- 19.6已完成：管理员总览增加80%额度预警用户、shadow would-block和预留低估计数，
  保持脱敏只读。普通管理员调整API继续403且页面不显示入口；超级管理员表单只保留
  Token、请求、可选费用覆盖值和原因，删除计划/套餐输入。清空覆盖恢复内部默认计划
  数字；每次调整写前后值和原因审计，目标用户角色不变。用户列表返回覆盖值用于正确
  区分“实际上限”和“人工覆盖”，不暴露购买或会员概念。
- 19.6验证：额度管理、权限、审计和迁移专项40项通过；完整后端443项、完整前端16文件
  59项通过。覆盖admin 403、super_admin调整/恢复默认、费用覆盖、两次审计、角色保持
  user，以及管理员/超级管理员页面按钮与表单边界。
- 19.7已完成：完整后端446项、完整前端16文件59项、SSE和正式构建通过；Alembic单一
  head、真实本地MySQL迁移往返/并发/恢复、敏感扫描、相对链接、差异、auth哈希及三角色
  三宽浏览器验收均通过。没有真实模型、SMTP、SSH、部署、commit或push。

## 5. 本任务阅读范围

下一任务先完整阅读`AGENTS.md`和本文件，再读取：

- `docs/quota-policy-v2-design.md`
- `docs/technical-design.md`第20、21节
- `docs/deployment.md`
- 当前Git差异、生产发布审计、0025迁移和环境开关配置

不要读取历史RAG评估JSON。发布必须先保持off，不自动启用enforce。

## 6. 唯一下一任务

**阶段19生产off发布。**

本小步按顺序执行：

1. 显式排除受保护的auth Service，提交并推送阶段19代码、迁移、页面、测试和文档。
2. SSH只读核对生产提交、0024、off开关、Compose配置和核心数据计数，随后创建并校验备份。
3. 显式写入`QUOTA_POLICY_MODE=off`，快进目标提交、上传已校验前端产物、重建backend/web。
4. 验证0025、四容器、HTTPS/HTTP、静态哈希、核心数据、受保护API和运行时off；不调用模型或SMTP。
5. off稳定后再根据自然流量提出shadow观察，不直接启用enforce。

继续禁止：

- 读取或输出真实密钥、调用真实Qwen/Embedding/Reranker/SMTP。
- 跳过off观察直接启用enforce。
