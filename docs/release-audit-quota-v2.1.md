# Quota v2.1 发布审计

> 发布日期：2026-08-01
>
> 功能提交：`02687b1d3c19a830709dc321682e8fa9e01fc95f`
>
> 生产迁移：`0025_quota_policy_v2 (head)`

## 1. 发布范围与策略

- 默认内部月额度从10万Token提高到100万Token，请求上限保持500。
- 发布`off/shadow/enforce`、RAG动态预留、Agent既有12000上限、可选费用限制、用户预警、
  管理员只读统计和超级管理员受审计调整。
- 系统角色仍只有`user/admin/super_admin`，没有引入会员、套餐用户或测试账号身份。
- 生产先以`off`完成迁移和黑盒验收，稳定后切到`shadow`；`enforce`没有启用。
- 没有修改RAG检索策略、Prompt、公共知识、Agent工具或SSE正文协议。

## 2. 发布前修复与验证

发布预检发现RAG动态估算发生在Quota Gate之前，使off/shadow在合法极限上下文下可能被
`QUOTA_RESERVATION_TOO_LARGE`阻断。修复后：off完全跳过RAG/Agent预留估算，shadow记录
未截断估算但继续调用，只有enforce能因单次估算超过策略上限拒绝。

- 额度与共享链路专项：31项通过。
- 完整后端：446项通过。
- 完整前端：16个文件、59项通过。
- SSE解析和Vite正式构建通过。
- Alembic唯一head为`0025_quota_policy_v2`；此前本地MySQL已完成`0024→0025→0024→0025`。
- `pip check`、`git diff --check`、敏感信息、文档相对链接和正式产物API地址检查通过。
- 受保护`backend/app/modules/auth/service.py`未进入功能提交，SHA-256保持
  `9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0`。

## 3. 备份与回滚

- 发布前完整备份：`/home/deploy/medical-rag-backups/backup-20260731T171945Z`，全部
  `SHA256SUMS`校验通过。
- 旧backend/web镜像以`rollback-phase19-20260731T171949Z`保留。
- 旧静态目录保存在`/home/deploy/release-assets/20260731T171949Z-pre-phase19`。
- 应用故障优先把`QUOTA_POLICY_MODE`恢复为off并恢复旧镜像；0025新增字段对0024应用向后
  兼容。只有确认数据库结构本身异常时才降级，降级前必须再次备份，因为会删除shadow事件。

## 4. 生产迁移与数据

迁移前生产为`a1a3853`和`0024`，13个用户、8个会话、134条消息、27份文档、18条usage、
1条默认计划、2个当前周期、0条assignment和0条reservation。两个周期均无人工覆盖。

迁移后：

- Alembic为`0025_quota_policy_v2 (head)`。
- 仍为13个用户、8个会话、134条消息、27份文档、18条usage、27个上传文件和103个
  Chroma片段。
- 仍为2个周期、0条assignment、0条reservation；两个当前默认周期均提高到100万Token。
- free计划为100万Token/500请求，默认费用上限为空；迁移没有重置使用量或创建策略事件。

## 5. 线上无费用验收

- 四个容器均为healthy；HTTPS首页、登录、个人中心、管理员用量和健康接口为200，HTTP
  固定308跳转HTTPS，三个受保护接口未登录为401。
- 线上`index.html`、JavaScript和CSS的SHA-256与本地正式构建完全一致；JavaScript包含
  `/api/v1`且不包含`127.0.0.1:8000`。
- off运行约4分钟并连续三次健康检查无错误，随后只重建backend切换到shadow。
- shadow运行时实测为`quota_policy_mode=shadow`、旧布尔开关false、自动记忆提取false；
  切换后数据计数保持，策略事件和reservation仍为0。
- 没有调用真实Qwen、Embedding、Reranker或SMTP，没有创建、删除或修改生产账号。
- 内置浏览器加载公网IP时控制连接超时；curl、容器静态资源和本地/线上哈希均正常，因此
  没有把本次线上三宽自动点击验收写成通过。本地1440/1280/390验收此前已通过。

## 6. 尚未完成的观察

shadow刚启用时尚无自然流量样本。后续只观察自然发生的RAG/Agent调用，包括would-block、
预留低估、unknown、过期reservation和数据库错误；不为了制造样本主动调用付费模型。
enforce必须在观察样本充分且没有P0/P1问题后另行评估，当前不得视为已启用。
