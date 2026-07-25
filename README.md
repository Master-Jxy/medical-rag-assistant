# Medical RAG Assistant

一个面向医学资料学习与内部知识检索场景的前后端分离 RAG 应用。系统支持 PDF/TXT 文档管理、向量检索、流式问答、引用来源、多轮会话和刷新恢复。

> 本项目仅用于技术学习和信息检索，不提供临床诊断、处方或治疗建议。

## 当前状态

**核心 RAG、用户治理、资料审核和管理中台已完成，云端恢复能力正在收口。**

当前已实现：

- FastAPI + Vue 3 前后端分离。
- PDF/TXT 上传、解析、递归切分和 SHA-256 内容去重。
- DashScope Embedding、Chroma 持久化向量检索。
- 通义千问回答、知识不足拒答和可展开的引用来源。
- SSE 流式输出、停止生成和安全错误事件。
- MySQL + SQLAlchemy 持久化会话、消息和来源。
- Alembic 数据库迁移基线，以及用户表、邮箱唯一约束和 Argon2 密码哈希。
- 邮箱注册、登录、短期 Bearer JWT 和当前用户接口。
- Vue 注册登录、刷新恢复、退出、路由守卫和统一 401 失效处理。
- 会话归属当前用户，跨账号列表、读取、修改、删除和问答统一隔离。
- MySQL 文档登记、公共知识库和系统文档保护；普通用户提交资料后先进入隔离审核区，不再直接写生产 Chroma。
- 数据库可信的 `user/admin/super_admin` 三层角色、集中权限策略、最后超级管理员保护和安全审计。
- 个人中心、“我的资料”、管理员审核、知识资产、处理任务、审计和超级管理员用户治理接口。
- 审核批准使用原子状态抢占、共享文档生命周期和可补偿发布；发布后的隔离文件清理失败只记录待清理告警。
- 知识资产支持来源、标签、版本、替换、下线与重发；只有 `published` 资料进入公共检索。
- 系统文档新增、删除、整份替换，以及 MySQL/文件/Chroma 失败补偿。
- Redis 连接适配器和 `ok/disabled/degraded` 健康状态；健康接口可区分限流/上传本机兜底与生成锁/幂等不可用，并记录去重的降级与恢复状态。
- 注册、登录按 IP 限流，以及四个问答入口共享的按用户限流；Redis 故障时使用有界本机兜底。
- 普通上传按用户限制频率与并发；管理员系统文档上传不限制每小时次数，但仍使用带所有权令牌和 TTL 的并发占位，一次只处理一个文件。
- 同一用户同一会话只允许一个生成任务，使用随机所有权令牌、有限 TTL 和原子比较释放。
- 会话问答使用 `Idempotency-Key` 防止网络重试重复创建消息或调用模型，完成结果通过 MySQL 资源 ID 恢复而非缓存完整回答。
- 最近 3 轮有效上下文、刷新恢复和历史会话管理。
- 后端 pytest、Vue 组件测试、SSE UTF-8 分片测试和生产构建验证。
- Docker Compose 编排 MySQL、Redis、FastAPI 和 Vue/Nginx，具备持久卷、健康检查、资源上限和统一公网入口。
- 已在 Ubuntu 22.04、2 核 2G 阿里云 ECS 完成 HTTP 部署基线与注册、登录、会话链路验收。
- 已建立带清单、SHA-256和保留上限的自动备份与受控恢复脚本；四类数据隔离恢复演练、生产首份备份和整机重启恢复通过。
- 版本化 `corpus_v1` / `eval_v1`、只读真实基线、人工复核、检索排序指标和费用闸门。
- 默认关闭的混合检索与Reranker实验能力；真实评估没有证明整体收益，因此生产继续使用冻结向量基线。
- `RAG v1.2.1` 已发布到GitHub并同步演示服务器，服务器免费验收和后端容器重启恢复通过。
- 已完成结构化JSON日志、阶段耗时、聚合指标、日志轮转以及管理员只读统计接口和页面，并作为`RAG v1.3`提交、推送和部署。

尚未实现，不能当作当前功能宣传：

- 独立受控资料整理 Agent。
- HTTPS和正式域名。

## 系统架构

```mermaid
flowchart LR
    U["用户"] --> V["Vue 3"]
    V -->|"REST / SSE"| F["FastAPI"]
    F --> S["应用服务"]
    S --> M[("MySQL")]
    S --> C[("Chroma")]
    S --> Q["通义千问"]
    S --> E["DashScope Embedding"]
    S --> D[("文件存储")]
```

主要数据流：

```text
资料提交 -> 隔离保存与解析预览 -> 管理员审核 -> 切片/Embedding -> Chroma -> MySQL发布登记
用户提问 -> 读取会话历史 -> 召回片段 -> 组装 Prompt -> 模型流式生成 -> 保存 MySQL -> 展示引用
```

项目采用**模块化单体**：保持一个应用易于运行和部署，同时约束路由、服务、数据库、向量库和 Agent 的依赖方向，避免功能增长后相互耦合。

## 技术栈

| 模块 | 技术 |
| --- | --- |
| 前端 | Vue 3、Vite、Element Plus、Axios |
| 后端 | Python、FastAPI、Pydantic、Uvicorn |
| RAG | LangChain、通义千问、DashScope Embedding、Chroma |
| 数据 | MySQL、SQLAlchemy、PyMySQL |
| 实时响应 | Server-Sent Events (SSE) |
| 测试 | pytest、Vitest、Vue Test Utils、happy-dom |

## 页面

- **系统概览**：服务状态和主要入口。
- **工作台 / 个人中心 / 我的资料**：查看个人统计、账号信息和资料审核进度。
- **知识问答**：新建、切换、重命名、删除会话，流式查看回答和引用来源。
- **公共知识库**：提交 PDF/TXT、查看已发布资料；提交成功不等于已发布。
- **管理中台**：审核、知识资产、任务、审计、系统资料与运行统计。
- **超级管理**：用户角色和账号状态治理。

## 目录

```text
medical-rag-assistant/
|-- backend/
|   |-- app/
|   |   |-- api/              # FastAPI 路由
|   |   |-- core/             # 配置、异常、模型工厂、SSE
|   |   |-- db/               # SQLAlchemy 基础设施
|   |   |-- infrastructure/   # Chroma 等外部系统封装
|   |   |-- models/           # 数据库模型
|   |   |-- schemas/          # API 请求/响应结构
|   |   `-- services/         # 当前业务服务
|   |-- scripts/              # 本地批量导入工具
|   |-- tests/
|   `-- requirements.txt
|-- frontend/
|   |-- src/
|   |   |-- api/
|   |   |-- router/
|   |   `-- views/
|   `-- tests/
|-- docs/
|   |-- project-vision.md
|   |-- technical-design.md
|   |-- development-roadmap.md
|   |-- product-and-ui-design.md
|   `-- handoff.md
|-- AGENTS.md
`-- README.md
```

## 本地运行

### 环境要求

- Python 3.11+
- Node.js 20+
- MySQL 8+
- 可用的 DashScope API Key

### 1. 后端环境

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `backend/.env`，至少配置：

```env
DASHSCOPE_API_KEY=your_dashscope_api_key_here
DATABASE_URL=mysql+pymysql://user:password@127.0.0.1:3306/medical_rag?charset=utf8mb4
JWT_SECRET_KEY=replace_with_a_random_secret_at_least_32_characters_long
```

创建数据库：

```sql
CREATE DATABASE medical_rag CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

创建或升级表结构：

```powershell
python -m alembic -c alembic.ini upgrade head
```

仅从旧版 `documents.json` 升级的已有项目，再执行一次登记迁移；脚本会核对现有文件和 Chroma 片段，不会重新调用 Embedding，重复执行也不会重复导入：

```powershell
python -m scripts.migrate_document_registry
```

启动后端：

```powershell
python -m uvicorn app.main:app --reload
```

- API：<http://127.0.0.1:8000>
- OpenAPI：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/v1/health>

### 2. 前端环境

```powershell
cd frontend
npm install
npm run dev
```

- 页面：<http://127.0.0.1:5173>

上传和问答会调用付费模型接口。列表、删除、健康检查和使用假实现的自动化测试不会产生模型费用。

## 主要接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/health` | 健康检查 |
| POST | `/api/v1/auth/register` | 注册用户 |
| POST | `/api/v1/auth/login` | 登录并获取短期 Bearer JWT |
| GET | `/api/v1/auth/me` | 使用 Bearer JWT 获取当前用户 |
| POST | `/api/v1/chat` | 登录后的无历史普通问答，按用户限流 |
| POST | `/api/v1/chat/stream` | 登录后的无历史 SSE 问答，按用户限流 |
| POST | `/api/v1/documents` | 登录后上传公共文档并记录上传者 |
| GET | `/api/v1/documents` | 登录后获取公共文档及可删除状态 |
| DELETE | `/api/v1/documents/{document_id}` | 仅上传者删除自己的文件、登记和向量 |
| GET/POST | `/api/v1/conversations` | 查询或创建会话 |
| GET/PATCH/DELETE | `/api/v1/conversations/{id}` | 会话详情、重命名、删除 |
| POST | `/api/v1/conversations/{id}/chat` | 带历史普通问答 |
| POST | `/api/v1/conversations/{id}/chat/stream` | 带历史 SSE 流式问答 |
| POST | `/api/v1/conversations/{id}/chat/stop` | 主动停止当前 SSE 回答，确认释放生成锁后恢复发送 |

## 测试

在项目根目录执行：

```powershell
backend\.venv\Scripts\python.exe -m pytest -q backend\tests
npm --prefix frontend test
npm --prefix frontend run test:stream
npm --prefix frontend run build
```

## 文档交接

即使更换 Codex 账号或开启全新对话，也不需要依赖旧聊天记录：

1. 新开发窗口先读 `AGENTS.md`。
2. 再读 `docs/handoff.md`，只执行其中的唯一下一任务。
3. 按handoff定向读取 `docs/development-roadmap.md` 的当前阶段和 `docs/technical-design.md` 的相关章节，不全文回放。
4. 页面、角色或交互任务再读 `docs/product-and-ui-design.md` 的对应章节。
5. `docs/project-vision.md` 只在产品范围变化时读取。
6. `docs/deployment.md` 与发布审计只在部署、验收或回滚任务中读取。

## 下一步

当前唯一下一任务始终以 `docs/handoff.md` 为准。当前总体顺序为：

```text
Platform v1.4治理能力发布
-> HTTPS与云端完整验收
-> 独立LangGraph资料Agent
-> 知识质量、可控记忆与复杂文档解析
```

每次只做一个可验证的小任务，详细范围以 `docs/handoff.md` 和 `docs/development-roadmap.md` 为准。

## 安全说明

- API Key、JWT 密钥、数据库密码和 `.env` 不提交 Git。
- 上传文件、Chroma、日志、数据库备份和真实用户数据不提交 Git。
- 后端错误不返回 Traceback、SQL、服务器路径或第三方密钥。
- 项目不提供临床医疗建议。

## AI 辅助开发说明

开发过程中使用 Codex 辅助需求拆解、代码实现、测试补充和问题定位。项目方向、功能取舍、架构边界、验收结果和最终代码由项目作者负责确认。
