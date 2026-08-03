# Stage 23 运行中断恢复发布审计

## 1. 发布范围

- 发布提交：684e4c1141ef0070470d38d10d1737d7d577174b。
- 变更范围：RAG 陈旧 pending 恢复服务、会话 API 首次恢复入口、900 秒配置约束、
  Compose 配置示例、自动化测试和 Stage 23 文档。
- 无数据库迁移、无前端源码变化、无模型调用、无生产开关切换。
- backend/app/modules/auth/service.py 的用户本地改动未暂存、未提交、未部署。

## 2. 发布前验证

- 后端：474 passed，113 warnings。
- 前端：18 files / 70 tests passed。
- SSE parser：passed。
- Vite production build：passed。
- git diff --check：passed。

## 3. 备份与同步

- 发布前服务器提交：92dd75144d7d3173ac374528a8c4422ac58c7cc8。
- 完整备份：/home/deploy/medical-rag-backups/backup-20260803T143105Z。
- mysql.sql.gz、app_data.tar.gz、chroma_data.tar.gz、redis_data.tar.gz、
  deploy.env、compose.yaml 和 manifest.txt 的 SHA-256 全部校验通过。
- 服务器通过 fast-forward 同步到 684e4c1，工作区保持干净。
- 只构建并替换 backend；MySQL、Redis、Web 和命名卷均未重建。

## 4. 线上验收

- 四个容器均为 healthy。
- HTTP 健康地址返回 308，HTTPS 健康地址返回 200。
- 未登录访问会话接口返回 401。
- backend 容器实际注入 RAG_PENDING_RECOVERY_AGE_SECONDS=900。
- 发布后 backend 日志未发现 traceback、exception、critical 或 error。
- 未创建生产测试账号或陈旧消息，不调用 Qwen、Embedding、Reranker 或 SMTP。
  陈旧状态数据路径由本地临时 SQLite 和 API 入口测试覆盖。

## 5. 回滚点

代码回滚目标为 92dd751，数据回滚材料为上述完整备份。正常回滚不得使用
docker compose down -v，也不得直接编辑服务器业务源码。
