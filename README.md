# Medical RAG Assistant

一个面向医学资料检索与知识问答场景的前后端分离 RAG 应用。用户可以上传 PDF/TXT 文档，系统完成解析、切分、向量化和持久化存储，并在问答时返回流式回答与可追溯的引用来源。

> 本项目用于技术学习和信息检索，不提供临床诊断或治疗建议。

## 项目亮点

- 基于 FastAPI 设计文档上传、列表、删除、会话管理和问答 API。
- 使用 LangChain、通义千问、DashScope Embedding 与 Chroma 实现完整 RAG 链路。
- 通过 SHA-256 内容哈希避免文档重复入库和重复向量化。
- 使用 SSE 将模型回答逐块推送到 Vue 页面，支持主动停止生成。
- 使用 MySQL + SQLAlchemy 持久化会话、消息和引用来源，刷新页面后可恢复历史对话。
- 读取最近 3 轮有效消息辅助连续追问，并限制历史上下文总长度。
- 对文档删除、流式状态、异常响应和请求标识进行了统一处理。
- 后端包含 pytest 测试，前端包含组件测试与 UTF-8 SSE 分片解析测试。

## 系统架构

```mermaid
flowchart LR
    U[用户] --> V[Vue 3 前端]
    V -->|REST / SSE| F[FastAPI]
    F --> D[文档与会话服务]
    F --> R[RAG 服务]
    D --> M[(MySQL)]
    R --> C[(Chroma)]
    R --> Q[通义千问]
    R --> E[DashScope Embedding]
```

核心数据流：

```text
文档上传 -> 格式校验 -> 文本解析 -> 递归切分 -> Embedding -> Chroma
用户提问 -> 历史上下文 -> 相似度检索 -> Prompt 组装 -> 大模型 -> SSE -> 引用来源
```

## 技术栈

| 模块 | 技术 |
| --- | --- |
| 前端 | Vue 3、Vite、Element Plus、Axios |
| 后端 | Python、FastAPI、Pydantic、Uvicorn |
| RAG | LangChain、通义千问、text-embedding-v4、Chroma |
| 数据库 | MySQL、SQLAlchemy、PyMySQL |
| 实时响应 | Server-Sent Events (SSE) |
| 测试 | pytest、Vitest、Vue Test Utils、happy-dom |

## 功能页面

- **系统概览**：展示项目入口和服务状态。
- **知识问答**：创建、切换、重命名和删除会话，流式展示回答与引用来源。
- **知识库管理**：上传 PDF/TXT、查看入库状态和片段数、删除文档及对应向量。

## 目录结构

```text
medical-rag-assistant/
|-- backend/
|   |-- app/
|   |   |-- api/              # FastAPI 路由
|   |   |-- core/             # 配置、异常、模型工厂与 SSE
|   |   |-- infrastructure/   # Chroma 向量库封装
|   |   |-- models/           # SQLAlchemy 数据模型
|   |   |-- schemas/          # Pydantic 请求/响应模型
|   |   `-- services/         # 文档、RAG 与会话业务逻辑
|   |-- tests/
|   `-- requirements.txt
|-- frontend/
|   |-- src/
|   |   |-- api/              # HTTP/SSE 接口封装
|   |   |-- router/
|   |   `-- views/            # 概览、问答、知识库页面
|   `-- tests/
|-- docs/                     # 设计文档
`-- README.md
```

## 本地运行

### 1. 环境要求

- Python 3.11+
- Node.js 20+
- MySQL 8+
- 有效的 DashScope API Key

### 2. 配置后端

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
```

创建数据库后启动后端：

```sql
CREATE DATABASE medical_rag CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

```powershell
python -m uvicorn app.main:app --reload
```

接口文档：<http://127.0.0.1:8000/docs>

### 3. 启动前端

```powershell
cd frontend
npm install
npm run dev
```

前端地址：<http://127.0.0.1:5173>

## 主要接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/health` | 健康检查 |
| POST | `/api/v1/documents` | 上传并向量化文档 |
| GET | `/api/v1/documents` | 获取文档列表 |
| DELETE | `/api/v1/documents/{document_id}` | 删除文件、登记信息和向量 |
| GET/POST | `/api/v1/conversations` | 查询或创建会话 |
| GET/PATCH/DELETE | `/api/v1/conversations/{id}` | 会话详情、重命名与删除 |
| POST | `/api/v1/conversations/{id}/chat` | 普通会话问答 |
| POST | `/api/v1/conversations/{id}/chat/stream` | SSE 流式会话问答 |

## 测试

```powershell
# 后端
cd backend
python -m pytest

# 前端组件测试
cd ..\frontend
npm test

# SSE 字节分片解析测试
npm run test:stream

# 生产构建
npm run build
```

## AI 辅助开发说明

开发过程中使用 Codex 辅助进行方案讨论、代码实现建议、测试补充和问题定位。项目需求拆解、架构选择、数据模型设计、接口联调、功能验收与最终代码审查由项目作者负责。

## 后续计划

- JWT 登录与多用户数据隔离。
- Redis 限流、缓存和重复任务控制。
- RAG 评估集、混合检索与 Reranker。
- Docker Compose 与云服务器部署。

## 安全说明

- API Key、数据库密码和 `.env` 文件不会提交到 Git。
- 本地上传文件、Chroma 数据、日志和数据库备份不会提交到 Git。
- 对外部署时应限制开放端口，并为模型接口增加身份验证和限流。
