# Stage 26 企业交付强化发布审计

> 发布日期：2026-08-11  
> 应用代码提交：`6c515e2fd06f0031d01dc4241f2392c7ef2082c0`  
> 上一生产提交：`b8e1719fa3be90b53822e58f07d2179737ae46b6`  
> 状态：已推送 GitHub、完成生产部署与黑盒验收

## 1. 发布范围

- Agent 图片草稿状态机、跨会话隔离、不可变提交快照和本地 URL 生命周期修复。
- `/livez`、`/readyz`、GitHub CI、统一发布预检和五服务 Compose 契约。
- 视觉幂等作用域、质量闸门、聊天 OCR 路由和无隐私固定图片评估。
- MySQL 租约队列、独立 Worker、有限重试、取消、崩溃租约回收和异步资料发布。
- `corpus_v2/eval_v2`严格质量门禁、六个确定性 Agent 工具、模型网关、真实模型目录、额度并发保护、低基数指标和 SLO 检查。

本次没有导入互联网医学正文、没有伪造黄金答案、没有启用多 Agent、没有执行真实 Embedding/Reranker/Qwen 评估，也没有删除或重建命名卷。

## 2. 发布前证据

- 仓库根目录完整后端：`688 passed, 1 skipped`。
- 前端：`22 files / 90 tests passed`；SSE parser、Vite production build、`pip check`和 Python compile 均通过。
- 迁移/Worker 专项：`22 passed`；ModelGateway/额度专项：`48 passed`；发布预检专项：`6 passed`。
- `npm audit --omit=dev --audit-level=high`：0 vulnerabilities。
- 本地 `/livez`、`/readyz`和发布预检通过；Compose解析为`mysql/redis/backend/worker/web`。
- 受保护文件SHA-256保持：`9468793f2264cd89f859f149bb72b7dca5d7941805a66e13d4cdaf6ddf7ba9b0`。
- 发布前外置备份：`/home/deploy/medical-rag-backups/backup-20260811T020551Z`，MySQL、app_data、Chroma、Redis、deploy.env、Compose和manifest共7项SHA-256全部通过。

## 3. 生产迁移与容器

- GitHub `main`已推送到应用提交`6c515e2`，服务器使用`deploy`用户快进拉取，未直接编辑线上业务源码。
- 数据库由`0030_multimodal_chat_assets`升级到`0033_stage26_job_leases (head)`，依次执行0031、0032和0033；没有降级或清库。
- 新backend完成迁移后先达到healthy，再启动worker和web。
- 最终运行服务：MySQL、Redis、Backend、Worker、Web；四个带healthcheck的服务均healthy，Worker为running，重启计数总和0。
- 生产策略保持保守：Agent和视觉聊天启用；OCR-mode、模型fallback、额度enforce和`/metrics`关闭；额度继续shadow观察。

## 4. 前端产物

`frontend/dist`不进入Git。首次服务器构建复用了旧dist，黑盒检查发现仍返回旧资源，因此按发布规范从本地上传已通过测试的正式构建并逐文件核对SHA-256，随后只重建web。

最终资源：

- `/assets/index-yKrn7dFv.js`
- `/assets/index-DrFkzane.css`

旧dist额外备份在`/home/deploy/medical-rag-config-backups/frontend-dist-20260811T0216`。该问题没有影响数据库、backend或worker。

## 5. 发布后验收

`deploy/post_release_check.sh`最终全部通过：

- `/livez`、`/readyz`；
- 五个容器running、重启计数0；
- 根分区使用33%，可用内存约428MiB；
- 最近10分钟严重错误标记0；
- 生产备份新鲜度通过；
- HTTPS证书剩余时间超过短期IP证书48小时门槛；
- `snap.certbot.renew.timer`为enabled/active。

生产浏览器使用临时无业务数据账号验证登录、Agent和RAG。新版资源明确加载，1440和390视口无横向溢出、无页面告警，textarea初始26px且Agent输入框自动聚焦；模型目录显示真实可用的`通义千问 qwen3-max`。没有发送消息、上传图片或调用模型。两个临时发布账号均在确认无Agent会话和RAG会话后删除。

## 6. 证书检查修复

Let’s Encrypt公网IP证书是约6天的短期证书，固定要求14天余量会永久失败。发布检查现按标识符选择默认门槛：公网IP48小时，普通域名14天，并允许运维显式覆盖；生产同时检查Certbot续期timer，避免仅凭当前证书有效就误判稳定。

## 7. 回滚点

- 应用回滚提交：`b8e1719fa3be90b53822e58f07d2179737ae46b6`。
- 数据回滚备份：`/home/deploy/medical-rag-backups/backup-20260811T020551Z`。
- 前端dist回滚目录：`/home/deploy/medical-rag-config-backups/frontend-dist-20260811T0216`。
- 0033后若已产生新任务数据，不盲目降级删列；优先停止worker、回退应用并按审计决定保留新表或恢复完整备份。

## 8. 已知边界

- `corpus_v2/eval_v2`真实状态仍为`not_eligible`：0份ready资料、0份人工黄金答案、10项覆盖缺口。
- 混合检索和Reranker仍未达到冻结晋级门槛，生产开关继续关闭。
- 模型fallback、OCR-mode、额度enforce和Prometheus抓取点均已具备代码边界，但未在本次发布中主动启用。

