# Memory v2.0 / Usage v2.0 发布审计

> 发布日期：2026-07-31  
> 功能提交：`93598397b4ab13d2712d4130785e913a9f635993`  
> 迁移恢复修复：`a1a38531ef067f9e7791f1982a7fe6b3b372312f`  
> 生产迁移：`0024_user_quota (head)`

## 1. 发布范围与开关

- 阶段17发布自动记忆候选、来源、冲突、敏感确认、修订历史及RAG/Agent统一
  `MemoryContextProvider`。
- 阶段18发布回答级usage、个人/管理员用量中心、MySQL额度计划、周期和原子reservation。
- `MEMORY_AUTO_EXTRACTION_ENABLED=false`和`QUOTA_ENFORCEMENT_ENABLED=false`；
  本次只发布代码、页面和兼容表结构，没有启用真实提取模型或生产额度拦截。
- 没有修改公共知识、RAG检索策略、Prompt、Agent工具、SSE正文协议、生产账号或业务数据。

## 2. 发布前验证

- 后端完整回归最终为426项通过；迁移与长`call_id`恢复专项16项通过。
- 前端14个文件、56项测试通过；SSE解析与Vite正式构建通过。
- Alembic唯一head为`0024_user_quota`；本地MySQL已完成`0021→0024→0021→0024`。
- `pip check`、`git diff --check`、高风险敏感模式和文档相对链接检查通过。
- 1440、1280和390宽本地真实浏览器验收通过。
- `backend/app/modules/auth/service.py`未进入发布提交，工作区原文件SHA-256保持
  `9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0`。

## 3. 备份与回滚

- 发布前完整备份：
  `/home/deploy/medical-rag-backups/backup-20260731T004301Z`。
- `mysql.sql.gz`、`app_data.tar.gz`、`chroma_data.tar.gz`、`redis_data.tar.gz`、
  `deploy.env`、Compose和manifest全部通过`SHA256SUMS`校验。
- 旧镜像：
  `medical-rag-backend:rollback-f076dd0-20260731T0045Z`和
  `medical-rag-web:rollback-f076dd0-20260731T0045Z`。
- 旧前端静态目录：
  `/home/deploy/release-assets/20260731T0045Z-pre-phase18`。
- 回滚先关闭两个新开关并恢复旧应用镜像；只有确认新表结构造成问题时，才按
  `0024→0023→0022→0021`降级或使用已校验备份恢复。

## 4. 迁移故障与恢复

首次生产迁移在`0023_usage_groups`回填阶段发现一条历史阶段16`call_id`超过36字符，
直接写入`VARCHAR(36)`触发MySQL 1406。由于MySQL DDL非事务，`0023`的列和索引已经添加，
Alembic版本停在`0022`；backend重试后报重复列。

发布立即停止重试并检查了第一次有效错误、Alembic版本和实际列集合。修复改为：

- 为历史调用生成确定性UUID分组ID，不截断或伪造Token。
- 迁移在恢复时检查已存在列和索引，只补缺失结构，再完成空值回填。
- 新增长`call_id`与部分DDL状态回归测试。

修复后的backend从`0022`半状态继续完成`0023`和`0024`，没有恢复数据库备份，也没有
删除、重建或覆盖既有业务表。

## 5. 线上结果

- 生产源码快进到`a1a3853`，仓库工作树干净；四个容器最终均为healthy。
- HTTPS首页、登录、个人中心和管理员用量路由返回200；HTTP固定返回308。
- 健康接口返回200；记忆、额度、管理员用量、会话和Agent线程接口未登录均返回401。
- 正式静态文件SHA-256与本地构建一致：
  - `index.html`：`637e6c2d06ac66dae39b8bc17b1350843b7ae4450d8732e53cd847c93c01e9e8`
  - JavaScript：`721ddefffacd3a81e22b5b7f0a053c72abf18f87fdbd7cf05635d6f92cc6c787`
  - CSS：`11c3f9125590bc98499df626d692779decec8dd00b75499b526b3fef503ab0e1`
- 迁移前后保持13个用户、7个会话、126条消息、27份文档、8条usage、27个上传文件和
  103个Chroma片段；8条历史usage均有36位分组ID。
- 新建1条默认额度计划；额度周期、reservation和记忆提取任务均为0。
- 没有调用Qwen、Embedding、Reranker或SMTP，没有创建、删除或修改生产账号。

## 6. 尚未执行的独立验收

- 自动线上可视浏览器在加载公网IP页面时控制连接超时；本机HTTPS请求和服务器DOM资源
  均正常，因此不能把线上1440/1280/390自动点击验收写成通过。
- 真实记忆提取模型usage、真实额度拦截以及真实RAG/Agent计量未执行；启用任一生产开关
  前仍需新的影响、费用、停止条件和回滚预检。
