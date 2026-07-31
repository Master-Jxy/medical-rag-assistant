# 当前开发交接

> 最后更新：2026-07-31
> 本文件只保留当前事实、工作区边界和一个下一任务。

## 1. 当前真实状态

阶段17和阶段18已完成全部本地代码、迁移、页面和无费用验证，**尚未发布、尚未启用生产
开关**。

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
  1440/1280/390浏览器验收完成。发布、服务器备份和生产迁移未执行。

## 2. 数据库迁移

- `0022_memory_v2`
- `0023_usage_groups`
- `0024_user_quota`（当前唯一head）

本地MySQL最终验证：

```text
0021 -> 0024
0024 -> 0021
0021 -> 0024
```

迁移往返当时前后核心数据均为4个用户、2个会话；之后浏览器验收新增2个本地测试账号。
迁移命令没有删除既有用户或会话。双线程同时
争抢只够一次的额度时结果为1次reserved、1次rejected；并发测试只创建并清理了本次临时
用户。

## 3. 验证证据

```text
backend\.venv\Scripts\python.exe -m pytest -q backend/tests
424 passed

D:\Nodejs\npm.cmd --prefix frontend test
14 files / 56 tests passed

D:\Nodejs\npm.cmd --prefix frontend run test:stream
SSE parser test passed

D:\Nodejs\npm.cmd --prefix frontend run build
Vite production build passed
```

其他检查：

- 阶段17/18记忆、额度与集成专项测试：17 passed，直接覆盖来源归属、内容去重、冲突
  修订、not_applicable零扣减以及失败流unknown保守结算。
- Alembic单一head：`0024_user_quota`。
- `git diff --check`通过，仅有Windows LF/CRLF提示。
- 敏感扫描只命中README/示例配置中的明确占位符，没有真实密钥、授权码或本地浏览器
  测试密码进入仓库。
- 文档相对链接目标全部存在。
- `backend/app/modules/auth/service.py`保持任务开始前SHA-256
  `9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0`。
- 浏览器实际`window.innerWidth`为1440、1280、390；个人记忆/用量和管理员用量页均无
  页面级横向溢出，移动端侧栏抽屉可打开，宽表在局部容器横向滚动，额度对话框完整位于
  390宽视口内。
- 浏览器验收发现并修复管理员空筛选参数触发422的问题，新增前端回归测试。

## 4. 工作区与安全边界

- 工作区保留开始前未提交修改；未回退、覆盖或格式化受保护的auth Service。
- 本地浏览器验收新增`phase18-ui-user@example.com`和
  `phase18-ui-super@example.com`测试账号；没有删除任何既有账号或业务数据。
- 没有调用真实Qwen、Embedding、Reranker、SMTP；没有SSH、部署、生产迁移、提交或推送。
- `MEMORY_AUTO_EXTRACTION_ENABLED`和`QUOTA_ENFORCEMENT_ENABLED`仍默认关闭。
- 真实提取模型usage、真实生产额度闸门、服务器备份/恢复和线上页面仍未验收，不能把
  本地完成写成已经上线。

## 5. 本任务阅读范围

下一任务只需完整阅读`AGENTS.md`和本文件，再读取：

- `docs/deployment.md`
- `docs/memory-and-quota-design.md`第8、10、11节
- 三个新迁移、功能开关、部署Compose和发布审计模板

## 6. 唯一下一任务

**阶段17/18生产发布预检：只做只读基线、备份/回滚方案、迁移影响、开关与无费用验收
计划；未经用户当次明确确认，不部署、不迁移生产、不启用开关、不调用真实模型。**
