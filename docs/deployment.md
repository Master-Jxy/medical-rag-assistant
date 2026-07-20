# 云端部署与更新手册

本文是 `medical-rag-assistant` 的可重复部署说明。真实密钥、数据库密码和线上数据不得提交 Git。

## 1. 当前部署基线

- 系统：Ubuntu 22.04 x86_64，建议至少 2 核 2G、40G 系统盘和 2G Swap。
- 入口：Nginx 只开放 `80`，`/` 提供 Vue 静态页面，`/api/v1` 反向代理 FastAPI。
- 内部服务：FastAPI、MySQL 8.0、Redis 6.2，不映射公网端口。
- 持久数据：`mysql_data`、`redis_data`、`app_data`、`chroma_data` 四个 Docker 卷。
- 外部模型：通义千问和 DashScope Embedding，密钥由 `deploy/.env` 注入。
- 当前限制：仅有 HTTP；域名、HTTPS、自动备份和完整重启恢复验收尚未完成。

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

## 4. 构建前端

当前国内镜像加速器不一定包含 Node 官方镜像，因此先在本地构建 Vue：

```powershell
$env:VITE_API_BASE_URL='/api/v1'
D:\Nodejs\npm.cmd --prefix frontend ci
D:\Nodejs\npm.cmd --prefix frontend run test
D:\Nodejs\npm.cmd --prefix frontend run build
```

将生成的 `frontend/dist` 上传到服务器仓库的同名位置。`dist` 不提交 Git，但构建 Nginx 镜像时必须存在。

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

### 6.1 RAG v1.2.1里程碑发布闸门

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
- 建立 MySQL、Chroma、上传文件和 Redis 的备份及恢复脚本。
- 上传正式知识文档，完成一次真实 RAG 流式问答与引用验收。
- 重启服务器后验证用户、会话、文档、向量和 Redis 数据仍存在。
- 固化版本回滚步骤，完成后再冻结 `Cloud v2.1`。
