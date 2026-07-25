# 云端部署与更新手册

本文是 `medical-rag-assistant` 的可重复部署说明。真实密钥、数据库密码和线上数据不得提交 Git。

本文件只在部署、线上验收、备份恢复或回滚任务中读取。普通后端、前端和RAG开发不要把部署历史作为每步必读上下文；当前唯一任务以 `docs/handoff.md` 为准。

## 1. 当前部署基线

- 系统：Ubuntu 22.04 x86_64，建议至少 2 核 2G、40G 系统盘和 2G Swap。
- 入口：Nginx 只开放 `80`，`/` 提供 Vue 静态页面，`/api/v1` 反向代理 FastAPI。
- 内部服务：FastAPI、MySQL 8.0、Redis 6.2，不映射公网端口。
- 持久数据：`mysql_data`、`redis_data`、`app_data`、`chroma_data` 四个 Docker 卷。
- 外部模型：通义千问和 DashScope Embedding，密钥由 `deploy/.env` 注入。
- 当前生产运行`Platform v1.4`；自动备份、隔离恢复演练和整机重启恢复已经通过。
- 当前限制：仅有 HTTP，域名和HTTPS尚未完成；正式域名必须由用户持有，`sslip.io`
  只能作为临时演示DNS别名。

## 2. 服务器首次准备

安装 Docker 和 Compose，并确认：

```bash
docker --version
docker compose version
systemctl is-active docker
```

小内存服务器建议增加 2G Swap。国内服务器若无法访问 Docker Hub，在 `/etc/docker/daemon.json` 配置自己的阿里云镜像加速地址，然后重启 Docker。

安全组只需要开放 SSH `22`、HTTP `80`；配置 HTTPS 后再开放 `443`。不要开放 `3306`、`6379` 或 `8000`。

## 3. 准备代码和秘密

```bash
git clone https://github.com/Master-Jxy/medical-rag-assistant.git
cd medical-rag-assistant
cp deploy/.env.example deploy/.env
chmod 600 deploy/.env
```

编辑 `deploy/.env`，至少替换以下值：

- `DASHSCOPE_API_KEY`
- `JWT_SECRET_KEY`
- `MYSQL_PASSWORD`
- `MYSQL_ROOT_PASSWORD`

`JWT_SECRET_KEY` 和两个数据库密码应分别生成，不要复用。所有 Compose 命令都必须带：

```bash
docker compose --env-file deploy/.env ...
```

否则 Compose 会提示变量未设置。

`DASHSCOPE_MAX_RETRIES`是可选的模型客户端重试配置，默认值为2。受控付费验收要求零自动重试时，在`deploy/.env`中设置为0并重建后端；它不应作为密钥输出。删除该配置并重建后端即可恢复默认值。

## 4. 构建前端

当前国内镜像加速器不一定包含 Node 官方镜像，因此先在本地构建 Vue：

```powershell
$env:VITE_API_BASE_URL='/api/v1'
D:\Nodejs\npm.cmd --prefix frontend ci
D:\Nodejs\npm.cmd --prefix frontend run test
D:\Nodejs\npm.cmd --prefix frontend run build
```

将生成的 `frontend/dist` 上传到服务器仓库的同名位置。`dist` 不提交 Git，但构建 Nginx 镜像时必须存在。
上传前必须检查生产JavaScript包含`/api/v1`且不包含`127.0.0.1:8000`；否则公网浏览器会错误访问访问者本机后端。

## 5. 启动和检查

```bash
docker compose --env-file deploy/.env build
docker compose --env-file deploy/.env up -d
docker compose --env-file deploy/.env ps
curl -fsS http://127.0.0.1/api/v1/health
```

四个容器都应显示 `healthy`。公网检查：

```text
http://服务器公网IP/
http://服务器公网IP/api/v1/health
```

## 6. 发布新版本

1. 只在本地工作区开发并运行后端、前端测试与生产构建。
2. 提交并推送 GitHub，不直接在服务器编写业务代码。
3. 备份线上数据。
4. 服务器拉取指定提交，上传新的 `frontend/dist`。
5. 重建受影响服务并检查健康状态。

```bash
git pull --ff-only
docker compose --env-file deploy/.env build backend web
docker compose --env-file deploy/.env up -d
docker compose --env-file deploy/.env ps
```

Compose 更新不会主动删除命名卷。禁止使用 `docker compose down -v`，该命令会删除数据库、Redis、上传文件和向量库数据。

### 6.1 RAG v1.2.1里程碑发布闸门 `[已完成]`

任务7.7完成证据决定后、阶段8开始前，任务7.8按以下顺序同步GitHub和当前阿里云服务器：

1. 本地记录发布范围，确认阶段7全部新增代码、测试、无正文报告和文档都已纳入；`.env`、密钥、本地回答正文、上传文件、Chroma、数据库备份、缓存和`__pycache__`必须排除。
2. 运行完整后端、前端、SSE和正式构建，并记录发布提交SHA与当前线上提交SHA。没有明确的前后版本号不得更新服务器。
3. 经用户确认后提交并推送GitHub；服务器工作区必须保持干净，只能拉取该指定提交，禁止直接编辑业务代码。
4. 更新前分别备份并校验MySQL、`app_data`、`chroma_data`和必要的Redis持久数据。备份与恢复脚本尚未固化时，不得把“已经备份”写入验收结论。
5. 先重建后端并检查健康；前端有构建产物变化时再上传新的`frontend/dist`并重建`web`。不得删除或重建命名卷。
6. 依次验证健康接口、注册/登录、当前用户、会话列表、文档列表、上传与删除权限、真实SSE问答、引用、主动停止和刷新恢复；随后重启容器并验证用户、会话、文档和向量仍存在。
7. 任一关键验收失败时停止继续修改，使用记录的上一提交恢复代码，并根据数据差异决定是否恢复备份；不能在故障现场临时改线上源码。

任务7.7没有候选通过完整评估时，线上必须继续保持：

```text
RAG_HYBRID_SEARCH_ENABLED=false
RAG_RERANK_ENABLED=false
RAG_CANDIDATE_EXPANSION_ENABLED=false
```

如果只有一个候选通过全部门槛，只允许启用该候选所需的最小开关，并固定`candidate_pool_size=12`、每文档最多2片段、最终`top_k=4`；其他实验开关继续关闭。发布后不得根据几个临时页面问题再次调参。

## 7. 设置管理员

用户必须先通过网页完成普通账号注册，再由服务器上的受控命令提升角色。项目不提供公开的管理员注册接口。

```bash
docker compose --env-file deploy/.env exec backend \
  python3 -m scripts.set_user_role 已注册邮箱 admin --confirm
```

成功时输出 `role_updated`。用户随后退出并重新登录，即可看到系统管理入口。必须使用 `python3 -m scripts.set_user_role` 的模块方式；直接运行 `python3 scripts/set_user_role.py` 会因为 Python 导入路径不包含 `/app` 而找不到项目模块。

如需取消管理员权限，将命令中的 `admin` 改为 `user`。不要把真实邮箱、密码或令牌写进本文档和 Git。

## 8. 日志和故障定位

```bash
docker compose --env-file deploy/.env logs --tail=100 backend
docker compose --env-file deploy/.env logs --tail=100 web
docker stats --no-stream
df -h
free -h
```

- 首页打不开：先看 `web` 是否健康、安全组是否开放 80。
- `/api/v1/health` 失败：查看 backend 日志及 MySQL、Redis 健康状态。
- Compose 提示变量为空：命令缺少 `--env-file deploy/.env`。
- 镜像拉取超时：检查 Docker 镜像加速器，不要反复删除已成功拉取的镜像。

## 9. 尚未完成的上线验收

- 配置域名和 HTTPS，之后才使用正式密码或向他人开放注册。
- `deploy/backup.sh`和`deploy/restore.sh`已经提供备份恢复入口；隔离恢复演练、生产备份
  校验和整机重启恢复已经通过。
- 真实RAG流式问答、引用、主动停止和清理恢复已按独立费用确认完成；详细证据见发布审计。
- HTTPS启用后验证证书链、HTTP跳转、API、SSE代理、容器重启和证书续期演练，再冻结
  `Cloud v2.1`。

## 10. 自动备份与受控恢复

备份目录必须位于仓库和Docker卷之外。脚本默认写入
`/home/deploy/medical-rag-backups`，保留最近7份；可以通过环境变量调整：

```bash
cd /home/deploy/medical-rag-assistant
BACKUP_ROOT=/home/deploy/medical-rag-backups \
BACKUP_RETENTION_COUNT=7 \
bash deploy/backup.sh
```

每份成功备份包含：

- MySQL单事务逻辑转储。
- `app_data`、`chroma_data`和执行`SAVE`后的`redis_data`卷归档。
- 当次`deploy/.env`、`compose.yaml`、Git提交与工作区脏状态。
- `manifest.txt`和覆盖全部文件的`SHA256SUMS`。

备份先写入`.incomplete-*`目录，任一步失败会删除本次未完成目录；全部校验通过后才
原子改名为`backup-*`并执行保留策略。脚本不输出`.env`内容，也不调用模型。

恢复会清空目标项目的MySQL业务库和三个数据卷，属于破坏性操作。正常场景默认先再做
一份`pre-restore`安全备份；只有全新空项目或独立演练环境才允许显式跳过。必须同时
确认备份目录、目标Compose项目名和恢复动作：

```bash
bash deploy/restore.sh \
  --backup /home/deploy/medical-rag-backups/backup-YYYYmmddTHHMMSSZ \
  --confirm-project medical-rag \
  --confirm-restore
```

恢复脚本先校验清单和全部SHA-256，再停止`backend/web/redis`，恢复三个卷，重建
MySQL业务库并导入逻辑转储，最后等待四个服务恢复健康。`deploy.env`只作为灾难恢复
材料随备份保存，不会自动覆盖当前`deploy/.env`；在新服务器恢复时应先人工确认权限
为600并放置该文件。不得对唯一生产实例使用`--skip-safety-backup`。

服务器使用systemd每天执行一次，定时器带最多10分钟随机延迟并在关机错过后补跑：

```bash
sudo install -d -m 755 /usr/local/lib/medical-rag
sudo install -m 755 deploy/backup.sh /usr/local/lib/medical-rag/backup.sh
sudo install -m 644 deploy/systemd/medical-rag-backup.service \
  /etc/systemd/system/medical-rag-backup.service
sudo install -m 644 deploy/systemd/medical-rag-backup.timer \
  /etc/systemd/system/medical-rag-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now medical-rag-backup.timer
sudo systemctl start medical-rag-backup.service
sudo systemctl status medical-rag-backup.service --no-pager
sudo systemctl list-timers medical-rag-backup.timer --no-pager
```

首次手工触发后必须检查最新`backup-*`中的`SHA256SUMS`，并确认生产四个容器仍为
`healthy`。定时服务使用`deploy`账号；该账号必须只通过`docker`组访问本机Docker，
备份目录权限保持700，备份文件保持600。

## 11. 域名、HTTPS、续期和回滚

HTTPS继续由现有Nginx终止，不暴露FastAPI、MySQL或Redis。两个Compose覆盖层只改变
`web`服务：

- `compose.https-bootstrap.yaml`：保持HTTP业务可用，同时开放HTTP-01挑战目录。
- `compose.https.yaml`：挂载证书、增加443、把所有HTTP业务请求固定跳转到HTTPS。

不要在证书尚不存在时直接启用最终覆盖层，否则Nginx会因证书文件缺失而启动失败。
启用脚本先核对DNS、显式确认域名、验证本机挑战路径，再签发证书；只有证书存在后才
切换443。如果最终Nginx检查失败，脚本自动恢复HTTP挑战配置，不删除证书或数据卷。

Ubuntu 22.04先安装Certbot，并在云安全组开放TCP 443；80必须继续开放用于HTTP-01和
自动续期：

```bash
sudo apt-get update
sudo apt-get install -y certbot

cd /home/deploy/medical-rag-assistant
sudo bash deploy/enable_https.sh \
  --domain demo.example.com \
  --email operator@example.com \
  --expected-ip 203.0.113.10 \
  --confirm-issue demo.example.com
```

首次签发前可以增加`--staging`验证流程，但测试证书不受浏览器信任，正式启用仍需再
执行一次不带`--staging`的命令。域名、邮箱和公网IP不是密钥，但真实联系人不写入Git。
用户未提供自有域名时，可使用形如`203-0-113-10.sslip.io`的临时演示别名；文档和简历
必须明确其非自有正式域名。

安装续期部署钩子并确认Ubuntu自带计时器：

```bash
sudo install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
sudo install -m 755 deploy/reload_nginx_after_renewal.sh \
  /etc/letsencrypt/renewal-hooks/deploy/reload-medical-rag-nginx.sh
sudo systemctl enable --now certbot.timer
sudo certbot renew --dry-run
```

验收至少包括：

```bash
curl -I http://demo.example.com/
curl -fsS https://demo.example.com/api/v1/health
openssl s_client -connect demo.example.com:443 \
  -servername demo.example.com -verify_return_error </dev/null
docker compose --env-file deploy/.env \
  -f compose.yaml -f deploy/compose.https.yaml ps
```

必须确认HTTP返回308且`Location`指向固定域名，证书SAN匹配、证书链验证通过，HTTPS
健康接口200，SSE没有被缓冲。然后重启`web`以及整台服务器各一次，复查证书和四类
持久数据。

需要恢复纯HTTP时使用显式确认命令。它只重建`web`为基础Compose配置，保留证书、
ACME目录、backend和四个数据卷：

```bash
sudo bash deploy/disable_https.sh \
  --domain demo.example.com \
  --confirm-disable demo.example.com
```
