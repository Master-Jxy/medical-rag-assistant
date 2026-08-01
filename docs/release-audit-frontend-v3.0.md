# Frontend v3.0 发布审计

> 发布日期：2026-08-01
>
> 功能提交：`84cf121f6d82b88fa53d6e3fa2eb00c958e8af60`
>
> 数据库：`0025_quota_policy_v2 (head)`，本次无迁移

## 1. 发布范围

- 重构AppShell、RAG/Agent聊天工作台、用户端、个人中心和管理中台的视觉与响应式交互。
- 引入`@lucide/vue`，新增统一确认框和模态框，移除业务页面的`window.prompt/confirm`。
- 保留全部FastAPI接口、权限、SSE、RAG、Agent、记忆、额度和数据语义。
- 本次只重建生产`web`容器，没有重建backend、MySQL或Redis，也没有修改持久卷。

停电中断的并行任务共享同一工作区，没有独立待合并分支；最终发布以主任务整合后的提交、
完整测试和浏览器验收为准，不以子任务是否生成最终回复作为完成依据。

## 2. 发布前验证

- 后端：446项通过，94条依赖弃用警告，无失败。
- 前端：16个文件、59项通过；SSE解析和Vite正式构建通过。
- `pip check`通过，Alembic单一head为`0025_quota_policy_v2`。
- 正式JavaScript包含`/api/v1`且不包含`127.0.0.1:8000`或`localhost:8000`。
- 1440、1280、900和390宽本地浏览器验收通过，无页面级横向溢出，控制台无错误或警告。
- 受保护auth Service SHA-256保持
  `9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0`。

## 3. 备份与回滚

- 完整生产备份：`/home/deploy/medical-rag-backups/backup-20260801T041805Z`。
- `mysql.sql.gz`、`app_data.tar.gz`、`chroma_data.tar.gz`、`redis_data.tar.gz`、
  `deploy.env`、`compose.yaml`和`manifest.txt`全部通过SHA-256校验。
- 旧静态目录：`/home/deploy/release-assets/20260801T042725Z-pre-frontend20`。
- 旧web镜像已保留为`rollback-frontend20`时间戳标签。
- 备份保留阶段发现早期root所有目录阻断自动清理；已将仓库和历史备份属主统一恢复为
  `deploy:deploy`，后续定时保留策略可正常执行。

## 4. 线上验收

- 服务器仓库从`e068790`安全快进到`84cf121`，发布后工作树干净。
- backend、web、MySQL和Redis四个容器全部healthy。
- HTTP首页返回308并跳转HTTPS；HTTPS健康接口返回200且Redis保护状态正常。
- 首页、登录、RAG、Agent、知识库、个人中心和管理端代表路由共10项返回200。
- 当前用户、会话和管理员用量三个受保护API未登录均返回401。
- 线上`index.html`、JavaScript和CSS SHA-256与本地正式构建完全一致。
- web发布后日志没有error、crit、emerg或alert。
- 生产继续使用`QUOTA_POLICY_MODE=shadow`；额度强制和自动记忆提取仍关闭。

内置浏览器加载公网IP仍发生控制超时，与此前发布记录一致；本机HTTPS、服务器curl、
静态哈希和容器内文件均正常，因此不把线上自动可视点击写成通过，也不将其判定为站点故障。
