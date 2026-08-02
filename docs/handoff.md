# 当前开发交接

> 最后更新：2026-08-02
> 本文件只保留当前事实、工作区边界和一个下一任务。

## 1. 当前真实状态

阶段17、18和19已完成代码、迁移、页面、本地验证和生产发布。阶段19功能提交为
`02687b1d3c19a830709dc321682e8fa9e01fc95f`，生产数据库为
`0025_quota_policy_v2 (head)`，四容器healthy。默认额度为100万Token/500请求；生产先以
off完成迁移和无费用验收后已切到shadow观察，**enforce和自动记忆提取仍未启用**。

阶段20企业级前端重构已完成并发布生产，功能提交为
`84cf121f6d82b88fa53d6e3fa2eb00c958e8af60`。本轮只调整前端信息架构、视觉、
响应式交互和组件测试，没有修改FastAPI接口、权限、RAG、Agent、记忆、额度或数据库行为：

- AppShell完成分组侧栏、桌面折叠、移动抽屉、面包屑、服务状态与账号菜单统一。
- RAG与Agent改为一致的双栏聊天工作台，并保留各自历史、SSE、停止、重试、来源和usage能力。
- 首页、认证、工作台、知识库、我的资料和个人中心完成统一；个人中心按账号、记忆、额度分区。
- 管理概览、审核、知识资产、任务、质量、监控、用量、系统资料和用户角色页面完成统一。
- 新增通用确认框与模态框，业务页面不再使用`window.prompt`或`window.confirm`。
- 浏览器已验收1440/1280/900/390四种宽度，页面级横向溢出为0，控制台error/warn为0。
- 完整验证为前端16文件59项、SSE解析、Vite正式构建及后端446项通过。
- 生产只重建`web`，backend、MySQL、Redis、四个持久卷和`0025`数据库结构保持不变；
  发布证据见`docs/release-audit-frontend-v3.0.md`。
- 设计与实现边界见`docs/frontend-redesign-v1.md`；发布提交未包含任务开始前已有的
  `backend/app/modules/auth/service.py`未提交修改。

阶段20长会话布局热修复已完成并发布，功能提交为`5c40ca29`：

- 根因是流式工作区仍使用可被长消息撑开的最小高度，页面滚动接管了消息区滚动。
- 顶栏以下的RAG/Agent工作区现在固定为当前可视高度；历史栏和消息区独立滚动，输入器
  始终留在聊天面板底部。移动端继续使用会话抽屉，不再重复计算整页视口高度。
- 对标新星数科控制台和AI聊天页后，只吸收稳定导航、独立滚动区、居中正文与固定输入器
  等布局思想；记录见`docs/ui-benchmark-xinxingshuke.md`，参考截图保存在Git忽略的
  `reference/ui-research/`目录。
- 本地使用无模型、无数据库写入的接口桩构造14条长消息，RAG和Agent在
  `1440x900`、`900x900`、`390x844`下均保持页面`scrollY=0`，消息区独立滚动，输入器
  与会话栏位置稳定；浏览器控制台应用错误为0。
- 完整验证为后端446项、前端16文件59项、SSE解析和Vite正式构建通过；受保护auth
  Service哈希仍为`9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0`。
- 发布前完整备份为`/home/deploy/medical-rag-backups/backup-20260801T052010Z`，旧静态目录
  保存在`/home/deploy/release-assets/20260801T0521Z-pre-layout-fix`。生产只重建`web`，
  backend、MySQL、Redis和持久卷未变；四容器healthy，HTTP为308，六个HTTPS代表路由
  为200，未登录`/api/v1/auth/me`为401，线上静态SHA-256与本地正式构建逐项一致。

阶段21视觉系统升级已完成开发、验证并发布生产，功能提交为`cf90eab`：

- 直接复用用户提供的SDWAN-GEO设计Token与玻璃材质规范，并借鉴新星数科控制台的
  侧栏占比、一主多辅指标层级、聊天独立滚动区和固定输入器；不复制品牌、Logo、文案、
  指标或源码。
- AppShell改为浮动玻璃侧栏、主信息顶栏和独立内容滚动区；全站统一蓝紫主操作、浅灰蓝
  画布、分级圆角、轻量状态色、控件状态和Reduced Motion。
- 工作台、知识库、认证、个人中心、RAG、Agent及管理页面复用同一视觉变量；保留原有
  API、权限、SSE、停止、重试、来源、usage、数据库和业务语义。
- 新增根目录`PRODUCT.md`与`DESIGN.md`，供后续Codex前端Skill直接读取产品事实和已落地
  视觉系统，避免新窗口重新猜测方向。
- 本地浏览器已验收`1440x900`、`1280x800`、`1024x768`、`390x844`；代表页面页面级
  横向溢出为0，RAG/Agent保持`scrollY=0`和固定输入器。
- 完整验证为前端16文件59项、SSE解析、Vite正式构建及后端446项通过；Impeccable规则
  扫描仅提示用户规范明确要求的Inter字体较常见，没有功能或可访问性阻断。
- 任务开始前已有的`backend/app/modules/auth/service.py`未提交修改保持原SHA-256
  `9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0`。
- 发布前完整备份为`/home/deploy/medical-rag-backups/backup-20260801T181237Z`，旧静态目录、
  发布压缩包和回滚镜像保存在`/home/deploy/release-assets/20260802T021309-frontend21`及
  `medical-rag-web:rollback-20260802T021309`。
- 生产仓库快进到`cf90eab`，只重建并重启`web`；backend、MySQL、Redis、Chroma、持久卷、
  环境变量和`0025`数据库结构未变。四容器healthy，HTTP为308，HTTPS首页、Agent和
  管理用量路由为200，未登录`/api/v1/auth/me`为401，线上index/JS/CSS SHA-256与本地
  正式构建逐项一致，线上登录页新Token生效且浏览器控制台无应用error/warn。

阶段21.1前端密度与公共概览优化已完成开发、验收并发布生产，功能提交为`d5bf4d6`：

- 修复`.public-shell footer`误作用于登录卡片内部页脚造成的竖排文字，公共页脚改为只匹配
  直属子元素；登录页在`1440x900`恢复正常横排。
- 桌面RAG/Agent移除与应用顶栏重复的标题卡，聊天面板直接位于顶栏下方；消息字号、
  行距和间距收紧，输入器一行起步、随内容增长且最高四行。移动端继续保留紧凑标题与
  会话抽屉入口。
- 个人中心默认进入“用量与额度”，标签顺序同步调整，不改变账号、记忆或usage接口。
- 未登录系统概览扩展为真实长页面，新增平台运行链路、技术生态横向轨道、能力矩阵、
  四步资料治理、角色工作区、滚动数字和部署架构；只展示可由项目源码证明的能力，不
  伪造客户、SLA、认证或商业指标。
- 本地浏览器验收`1440x900`与`390x844`：公共页滚动高度约`3872px/6274px`，横向溢出为0；
  数字进入视口后从0增长到`3/2/4/1`；RAG和Agent保持固定输入器及独立消息滚动。
- 前端16文件59项、SSE解析、Vite正式构建和`git diff --check`通过；Impeccable只提示
  用户参考明确要求的首屏网格与Inter字体。临时本地验收账号、额度周期及相关记录均已
  精确清理为0；没有调用模型或修改生产数据。
- 发布前完整备份为`/home/deploy/medical-rag-backups/backup-20260801T191730Z`；旧静态目录、
  新构建上传目录和回滚镜像保存在`/home/deploy/release-assets/20260801T1918Z-frontend211`
  及`medical-rag-web:rollback-20260801t1918z`。生产只重建`web`，backend、MySQL、Redis、
  Chroma、持久卷、环境变量和`0025`数据库结构未变。
- 发布时首次仅使用基础Compose重建Web，预检立即发现443映射缺失；随后按部署文档带
  `deploy/compose.https.yaml`覆盖层重新创建Web，恢复80到HTTPS的308跳转和443证书挂载。
  最终四容器healthy，HTTPS首页、登录、RAG和Agent路由为200，未登录`/api/v1/auth/me`
  为401，线上index/JS/CSS SHA-256与本地正式构建逐项一致，Web日志无应用错误。
- 应用内浏览器已成功请求线上首页、新CSS/JS和健康接口，但自动页面脚本读取受公网IP
  浏览器连接超时影响，未把线上可视DOM验收写成通过；本地同构构建的桌面/移动端可视
  验收与线上静态哈希一致性共同作为本轮视觉发布证据。

阶段21.2导航、知识资产和模型透明度改版已完成开发、验证并发布生产，功能提交为
`612c3c0`，生产仓库提交为`8d52929`：

- 公共顶栏新增`http://38.60.165.43/`中转站外链；桌面显示文字和图标，390px收敛为
  居中的外链图标。首页关键标题与公共登录按钮使用流动渐变；技术生态轨道悬停暂停，
  当前条目加深并轻微放大。
- 管理端删除独立“系统资料”菜单和页面，`/admin/knowledge`兼容重定向到统一
  `/admin/knowledge-assets`。统一页支持来源、状态、标签、治理状态筛选，并保留系统资料
  新增、整份替换、永久删除及知识资产编辑、下线、复核能力。
- 知识资产接口增加数据库真相字段`is_system`以及`review_status/expired`筛选，没有数据库
  迁移；顺带修复了朴素时间与带时区时间比较的兼容问题。
- 新增认证后的`GET /api/v1/models?surface=rag|agent`目录。当前只有通义千问启用，
  DeepSeek/Kimi为不可点击的测试中状态；菜单从后端读取当前模型及输入/输出单价，
  不传输密钥。RAG与Agent输入器复用同一选择组件。
- 回答底部用量改为分离显示模型实际Token、输入/输出、额度扣减和估算费用，继续区分
  `actual/unknown/not_applicable`与未配置单价。
- 登录行为只读核对后保持不变：JWT默认30分钟、无Refresh Token和单设备会话表，同一账号
  可多电脑登录，退出只清理当前浏览器，密码重置通过`token_version`使旧Token全部失效。
- 完整验证为后端`447 passed`、前端`17 files / 60 tests passed`、SSE解析和Vite正式构建
  通过；`git diff --check`通过。Impeccable一次扫描仅提示已批准的Inter回退字体、首页
  流动渐变文字和首屏网格背景，没有功能或可访问性阻断。
- 本地真实浏览器在`1440x900`和`390x844`验收首页、RAG、Agent、知识资产、筛选和治理
  弹窗；页面级横向溢出为0，模型单价为输入¥2.50/输出¥10.00每百万Token，禁用模型状态
  正确，控制台error/warn为0。临时超级管理员账号已精确删除，没有调用真实模型、
  Embedding、Reranker或SMTP。
- 任务开始前已有`backend/app/modules/auth/service.py`未提交修改保持SHA-256
  `9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0`。
- 发布前完整备份为`/home/deploy/medical-rag-backups/backup-20260802T140844Z`，MySQL、
  app_data、Chroma、Redis、环境文件和清单的SHA-256全部通过。GitHub直连超时后使用本地
  生成并验证的增量Git bundle将同一提交安全快进到服务器，生产工作树最终保持干净。
- 生产显式配置RAG与Agent输入¥2.50、输出¥10.00每百万Token；先重建backend并验证
  模型目录未登录401、登录态RAG/Agent目录、启用/测试中状态及单价，再上传与本地哈希
  一致的正式构建并重建web。MySQL、Redis和四个持久卷未重建，数据库仍为`0025`。
- 发布后四容器healthy，HTTP固定308到HTTPS，健康接口200，首页、登录、RAG、Agent、
  知识资产及旧兼容路由均为200。线上index/JS/CSS/图标哈希与本地逐项一致，backend/web
  日志无关键错误；线上桌面和390px移动端首页截图正常，浏览器控制台error/warn为0。
- 回滚静态目录和镜像保存在`/home/deploy/release-assets/20260802T141219Z-stage212`、
  `/home/deploy/release-assets/20260802T141850Z-stage212-web`及`rollback-stage212`镜像标签。
  `QUOTA_POLICY_MODE=shadow`、`QUOTA_ENFORCEMENT_ENABLED=false`和自动记忆提取关闭状态均
  保持不变；本次没有调用真实模型、Embedding、Reranker或SMTP，也没有修改业务数据。

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
- `0024_user_quota`
- `0025_quota_policy_v2`（当前代码、本地MySQL和生产唯一head）

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
- Alembic代码、本地MySQL与生产单一head：`0025_quota_policy_v2`。
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
- 阶段18发布当时保持27份文档、103个Chroma片段、27个上传文件；8条历史usage分组ID
  均为36位，默认额度计划1条，周期、reservation和提取任务均为0。
- 阶段19发布前生产已自然增长到13个用户、8个会话、134条消息和18条usage；迁移后这些
  数量以及27份文档、27个上传文件、103个Chroma片段全部保持。2个当前默认周期从10万
  安全提高到100万，assignment、reservation和策略事件均为0。
- 阶段19备份`/home/deploy/medical-rag-backups/backup-20260731T171945Z`及全部SHA-256
  通过；旧镜像和静态目录已保留。HTTPS/HTTP、401权限、静态哈希和四容器通过。
- off运行约4分钟且连续三次健康检查无错误后，backend受控切到shadow；运行时实测
  `quota_policy_mode=shadow`、旧布尔开关false、自动记忆提取false。切换没有主动调用模型，
  立即检查时usage仍为18、策略事件和reservation仍为0。
- 线上自动可视浏览器控制在加载公网IP时超时；本机HTTPS与服务器静态/DOM资源正常，
  因此没有把线上1440/1280/390自动点击验收写成通过。
- 阶段20发布前完整备份
  `/home/deploy/medical-rag-backups/backup-20260801T041805Z`全部SHA-256通过；旧静态目录保存在
  `/home/deploy/release-assets/20260801T042725Z-pre-frontend20`，旧web镜像已增加回滚标签。
- 阶段20生产仓库快进到`84cf121`且工作树干净；四容器healthy，HTTP为308，HTTPS健康
  接口和10个前端路由为200，3个受保护API未登录为401。线上index/JS/CSS与本地正式构建
  SHA-256一致，web近15分钟无error/crit/emerg/alert日志。
- 阶段20没有重建backend或执行迁移；运行时继续为`QUOTA_POLICY_MODE=shadow`、
  `QUOTA_ENFORCEMENT_ENABLED=false`、`MEMORY_AUTO_EXTRACTION_ENABLED=false`。

## 4. 工作区与安全边界

- 工作区保留开始前未提交修改；未回退、覆盖或格式化受保护的auth Service。
- 阶段19代码、迁移、测试和页面已提交推送并发布；发布审计见
  `docs/release-audit-quota-v2.1.md`。
- 本地浏览器验收新增`phase18-ui-user@example.com`和
  `phase18-ui-super@example.com`测试账号；没有删除任何既有账号或业务数据。
- 发布提交和迁移恢复提交已推送到GitHub并同步生产；服务器仓库工作树干净。首次
  ff-only因历史root所有权留下的半成品工作树已保存为服务器stash后重新安全快进。
- 没有调用真实Qwen、Embedding、Reranker、SMTP，没有创建、删除或修改生产账号。
- 阶段19只创建并随后精确删除了本地并发/浏览器验收账号；原有6个本地账号和业务数据
  保持。没有读取桌面授权码或其他真实凭据。
- `MEMORY_AUTO_EXTRACTION_ENABLED=false`、`QUOTA_ENFORCEMENT_ENABLED=false`和
  `QUOTA_POLICY_MODE=shadow`已在生产运行时实测。
- 真实提取模型usage和真实额度拦截仍未验收；shadow只观察自然流量，不能写成enforce
  已经启用。

阶段19已经完成开发、无费用验收和生产发布：默认额度计划提高到100万Token/月，保持500次
请求；增加off/shadow/enforce、RAG动态预留、可选费用闸门和三角色额度管理。系统角色
仍只有`user/admin/super_admin`，额度策略不创造新身份。完整设计见
`docs/quota-policy-v2-design.md`；生产当前为shadow观察，enforce未启用。

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
  三宽本地浏览器验收均通过。生产备份、迁移、容器、HTTPS、权限和静态哈希也已通过。

## 5. 本任务阅读范围

下一任务先完整阅读`AGENTS.md`和本文件，再读取：

- `docs/technical-design.md`的知识资产、资料审核和文档治理相关段落
- `docs/product-and-ui-design.md`的知识资产管理页面约束
- `backend/app/modules/knowledge/asset_service.py`
- `frontend/src/views/AdminAssetsView.vue`

不要读取历史RAG评估JSON，不主动制造付费模型流量，不自动启用enforce；知识分类方案
没有确认前不得引入模型调用或改变现有管理员人工选择语义。

## 6. 唯一下一任务

**阶段21.3知识分类与科室标签受控优化方案。**

先只做现状审计和方案设计：明确分类词表、科室标签来源、管理员人工选择与AI建议的边界、
历史资产回填、低置信度处理、审核日志和失败回退。默认采用“系统建议、管理员确认”而不是
模型自动发布；用户确认方案后再拆分后端契约、异步处理和前端交互任务。
