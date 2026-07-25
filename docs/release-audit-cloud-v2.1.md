# Cloud v2.1 发布与恢复审计

> 审计日期：2026-07-26
> HTTPS实现提交：`b323d18`至`21cda0e`
> 生产应用提交：`21cda0e6db8e1ea12219aff7dbd52a7bb6156d69`
> 状态：已完成生产部署、续期演练和整机重启验收

## 1. 发布范围

- MySQL、Redis、FastAPI和Vue/Nginx四容器健康、持久卷和资源上限基线。
- MySQL、`app_data`、`chroma_data`和`redis_data`自动备份、SHA-256清单、
  7份保留策略、受控恢复和隔离恢复演练。
- Nginx HTTP-01挑战、受信任HTTPS入口、HTTP 308固定跳转、SSE代理参数和纯HTTP回滚。
- Certbot自动续期、续期后Nginx热重载、web容器重启和整台服务器重启恢复。

不包含自有品牌域名、ICP备案、Agent或RAG质量调参。当前HTTPS证书标识符是公网IP
`112.124.9.120`；它是受信任安全入口，但不是正式品牌域名。

## 2. 发布前保护

- 生产全量备份：
  `/home/deploy/medical-rag-backups/backup-20260725T182511Z`。
- HTTP配置备份：
  `/home/deploy/medical-rag-config-backups/https-20260726T023000Z`。
- 配置备份目录权限700、文件600；`compose.yaml`、`nginx.conf`、容器状态、web镜像ID
  和Git提交5项SHA-256全部通过。
- HTTPS变更没有重建backend、MySQL、Redis或四个数据卷；旧HTTP配置和证书均可恢复。

## 3. 实现与故障证据

- HTTPS脚本要求显式确认域名或IP，只允许二选一；先保持HTTP并验证挑战目录，证书存在
  后才增加443，最终切换失败自动恢复HTTP。
- `112-124-9-120.sslip.io`的staging请求因一处验证视角得到403失败；Nginx实际收到
  其他验证器的200。没有把该临时DNS别名宣称为正式域名，也没有无限重试。
- Let’s Encrypt已支持短期公网IP证书；切换Certbot 5.7后，IP staging签发成功。首次
  production请求的三台验证器返回200，但另一secondary视角跨境连接超时；按上限只
  重试一次，第二次正式签发成功。
- 早期staging证书因Certbot目录参数缺失误写默认目录；只读确认其issuer含
  `(STAGING)`且标记`INVALID: TEST_CERT`后，用Certbot精确删除该测试lineage。脚本随后
  显式隔离`config/work/logs`目录，重跑成功。
- 正式证书issuer为Let’s Encrypt `YE1`，SAN为`IP Address:112.124.9.120`，链验证
  `Verify return code: 0`，有效至`2026-08-01 09:37:47 UTC`。

## 4. 自动化和生产验收

- 后端完整测试280项通过；前端9个文件31项通过；SSE分片和Vite正式构建通过。
- HTTPS部署边界测试覆盖ACME、TLS、固定跳转、SSE关闭缓冲、显式确认、staging隔离、
  IP短期证书、失败回滚和续期热重载。
- Snap Certbot 5.7续期timer为enabled/active；`renew --dry-run --run-deploy-hooks`
  成功并执行`nginx -s reload`。
- 外部TCP 443可达；HTTP返回308并保留路径/查询参数；HTTPS健康接口200。
- HTTPS真实SSE使用1次`text-embedding-v4`和1次`qwen3-max`、0次重试、0次Reranker，
  收到13个token事件、79字、4个来源、1个`done`和0个`error`。
- 真实浏览器打开`https://112.124.9.120/`，标题为`Medical RAG Assistant`、显示
  “运行正常”且没有证书警告页。
- web重启和整机重启后证书指纹不变、HTTP跳转和HTTPS健康正常，四容器healthy，
  Certbot timer仍为enabled/active。

## 5. 最终一致性

临时HTTPS验收账号无会话、提交或审计依赖，已删除；注册、登录和问答产生的3个Redis
限流键已清理。最终基线为：

```text
users=4
conversations=5
messages=42
documents=27
knowledge_submissions=27
document_versions=27
processing_jobs=0
audit_events=0
chroma_chunks=103
redis_keys=2
```

阶段十冻结为`Cloud v2.1`。正式品牌域名需要用户拥有域名并完成适用的DNS/备案流程，
属于后续运营配置，不再阻塞阶段十一的本地Agent开发。
