# 技术设计与演进架构

> 最后更新：2026-07-17
> 文档用途：说明当前真实实现、目标架构、数据契约和后续演进边界。
> 状态标记：`[现状]` 表示代码已经具备，`[目标]` 表示尚未实现，`[迁移]` 表示后续开发时逐步调整。

## 1. 设计目标

Medical RAG Assistant 是一个前后端分离的医疗资料检索与问答系统。项目需要同时展示：

- Python/FastAPI 后端接口设计能力。
- Vue 前端与 SSE 流式交互能力。
- MySQL 数据建模和事务处理能力。
- RAG 检索、引用来源和效果评估能力。
- 登录、限流、日志、部署等工程能力。
- Agent 工具编排能力，但不让 Agent 破坏原有问答链路。

本项目选择**模块化单体**，而不是微服务。所有模块仍由一个 FastAPI 应用启动，但业务边界清晰、依赖方向固定、可以独立测试。这个方案适合当前项目规模和 2 核 2G 演示服务器，也为后续拆分留下空间。

## 2. 文档与代码的真相顺序

当文档之间发生冲突时，按以下顺序判断：

```text
当前代码和自动化测试
-> docs/handoff.md
-> docs/development-roadmap.md
-> docs/technical-design.md
-> README.md
```

发现冲突的开发者必须在同一次任务中修正文档，不能继续堆积互相矛盾的说明。

## 3. 当前系统架构

### 3.1 当前组件

```mermaid
flowchart LR
    U["浏览器用户"] --> V["Vue 3"]
    V -->|"REST / SSE"| A["FastAPI"]
    A --> AU["认证与权限"]
    A --> CS["会话应用服务"]
    A --> KS["知识库应用服务"]
    A --> RS["RAG 应用服务"]
    A --> RL["RateLimitService"]
    RL --> RI["RedisInfrastructure"]
    AU --> M[("MySQL")]
    CS --> M
    KS --> M
    KS --> F[("上传文件")]
    KS --> C[("Chroma")]
    RS --> C
    RS --> Q["通义千问"]
    KS --> E["DashScope Embedding"]
```

Redis 已承载注册、登录、四个聊天入口的限流，普通上传的频率与并发保护、管理员上传的并发保护，以及带会话问答的生成锁与请求幂等。Agent 仍未实现，不能画进“当前组件”冒充现状。

### 3.2 当前后端目录

```text
backend/app/
|-- api/                    # FastAPI 路由
|   |-- health.py
|   |-- chat.py
|   |-- documents.py
|   `-- conversations.py
|-- core/                   # 配置、异常、模型工厂、SSE 格式
|-- db/                     # SQLAlchemy Base 和 Session
|-- infrastructure/         # Chroma 与 Redis 外部系统封装
|-- ports/                  # RateLimitPort 等跨模块小型能力契约
|-- modules/
|   |-- auth/               # 用户、密码哈希、JWT、认证依赖和路由
|   `-- knowledge/          # 文档登记、Repository 和共享生命周期
|-- models/                 # Conversation/Message/MessageSource
|-- schemas/                # Pydantic 请求与响应结构
|-- services/               # 逐步迁移中的文档、RAG、会话应用服务
`-- main.py                 # 正式 FastAPI 入口
```

当前结构能够支撑 MVP，但 `services/`、`models/` 和 `schemas/` 会随着功能增加而变得拥挤。因此后续新增或修改功能时，逐步迁移为按业务模块组织的结构。

### 3.3 当前前端目录

```text
frontend/src/
|-- api/                    # 后端接口封装
|-- router/                 # 页面路由
|-- views/                  # Home、Chat、Knowledge 页面
|-- App.vue
|-- main.js
`-- style.css
```

前端目前规模较小，暂不强制引入 Pinia。登录后如果跨页面共享用户状态明显增多，再建立 `stores/auth.js`；不能为了技术栈展示提前增加无用状态管理。

## 4. 当前已实现的调用链

### 4.1 页面进入

```text
浏览器访问地址
-> Vue Router 根据路径选择 View
-> View 在 onMounted 中调用 src/api 对应方法
-> API 模块拼接后端地址并发起请求
-> FastAPI 路由接收请求
-> Service 执行业务
-> 返回 JSON 或 SSE
-> Vue 更新页面状态
```

### 4.2 文档上传

```text
KnowledgeView 选择 PDF/TXT
-> documents.js 发送 multipart/form-data
-> Bearer JWT 解析当前用户
-> UploadProtectionService 消费用户频率额度并获取带 TTL 的并发占位
-> documents.py 校验请求
-> DocumentService 校验格式、大小和 SHA-256
-> 保存文件并解析文本
-> 文本切片
-> DashScope 生成 Embedding
-> VectorStoreService 写入 Chroma
-> MySQL documents 表登记文档和 uploader_id
-> finally 按所有权令牌释放并发占位
-> 返回文档摘要
```

文档上传涉及“文件、Chroma、登记表”三处写入。发生失败时必须清理已经写入的部分，避免出现页面有记录但向量不存在，或向量存在但页面不可见。

### 4.3 文档删除

```text
KnowledgeView 点击删除并二次确认
-> documents.js 发送 DELETE
-> Bearer JWT 解析当前用户
-> documents.py 调用 DocumentService
-> MySQL 查询登记并校验上传者
-> 系统文档或非上传者返回403
-> 暂存文件并快照该文档的 Chroma 片段
-> 删除 Chroma 片段和 MySQL 登记
-> 提交成功后删除暂存文件
-> 返回成功
-> 页面只移除被删除的项目
```

提交前失败时恢复 Chroma 快照和文件。删除测试必须同时检查：目标文件、目标登记项、目标向量均消失，其他文档保持不变。

### 4.4 带会话的流式问答

```text
ChatView 发送问题
-> conversations.js 发起 SSE 请求
-> Bearer JWT 解析当前用户
-> conversations.py 创建 request_id
-> ConversationChatService 同时按会话 ID 和当前 user_id 校验归属
-> 越权或不存在都返回404，不泄漏会话是否存在
-> 保存用户消息
-> 创建 pending 助手消息
-> 读取最近 3 轮有效历史
-> RagService 组合检索问题
-> Chroma 召回相关片段
-> 组装 Prompt 并流式调用通义千问
-> token 事件持续到达 Vue，同一气泡逐块增长
-> sources 事件补充引用来源
-> 完整回答、来源和状态一次性写入 MySQL
-> done 事件返回消息 ID 和 request_id
```

异常状态：

- `completed`：完整生成并成功保存。
- `stopped`：用户中断，保留已生成部分。
- `failed`：模型或流程失败，保存失败状态，不保存虚构来源。
- `pending`：生成中临时状态，不应作为后续上下文。

## 5. 当前 API 契约

所有业务接口统一使用 `/api/v1` 前缀。

| 方法 | 路径 | 当前用途 |
| --- | --- | --- |
| GET | `/health` | 低成本健康检查；返回 Redis 的 ok/disabled/degraded 及四类保护能力状态，不初始化 RAG |
| POST | `/auth/register` | 邮箱密码注册普通用户 |
| POST | `/auth/login` | 登录并签发短期 Bearer JWT |
| GET | `/auth/me` | 恢复当前用户及数据库角色 |
| POST | `/chat` | 无历史普通问答 |
| POST | `/chat/stream` | 无历史流式问答 |
| POST | `/documents` | 上传并向量化文档 |
| GET | `/documents` | 获取文档列表和统计 |
| DELETE | `/documents/{id}` | 删除文档、登记和向量 |
| POST | `/admin/documents` | 管理员新增系统文档 |
| PUT | `/admin/documents/{id}/replace` | 管理员整份替换系统文档 |
| DELETE | `/admin/documents/{id}` | 管理员删除系统文档 |
| POST | `/conversations` | 创建会话 |
| GET | `/conversations` | 分页获取会话 |
| GET | `/conversations/{id}` | 获取消息与来源 |
| PATCH | `/conversations/{id}` | 修改标题 |
| DELETE | `/conversations/{id}` | 级联删除会话 |
| POST | `/conversations/{id}/chat` | 带历史普通问答 |
| POST | `/conversations/{id}/chat/stream` | 带历史流式问答 |
| POST | `/conversations/{id}/chat/stop` | 按当前用户、会话和本次请求标识主动停止流式回答 |

登录完成后，除健康检查和注册/登录外，业务接口需要 Bearer Token。`/chat`、`/chat/stream` 与两个会话问答接口均按当前用户限流；前端主流程仍只使用带会话接口。

## 6. 当前数据设计

### 6.1 MySQL

```text
User 1 --- N Conversation 1 --- N Message 1 --- N MessageSource
```

- `Conversation`：会话 ID、非空用户外键、标题、创建时间、更新时间。
- `Message`：消息顺序、角色、正文、状态、请求标识。
- `MessageSource`：文件名、页码、原文片段等引用快照。
- 删除会话时，消息和来源通过级联关系一起删除。
- token 不逐条写数据库，结束或中断时一次性保存，降低写入次数。
- Alembic 当前版本为 `0005_user_role`：在 `0004_documents` 的公共文档登记基础上，`0005_user_role` 增加数据库可信的用户角色字段和约束。
- `User`：用户 ID、规范化邮箱、可选昵称、Argon2 密码哈希、启用状态、`user/admin` 角色和时间字段。

### 6.2 文档和向量

- 原文件保存到 `.env` 的 `UPLOAD_DIR` 对应目录。
- MySQL `documents` 表是文档主登记源，保存文件名、内容哈希、片段 ID、上传者、系统文档标记和状态。
- Chroma 保存片段向量和来源元数据。
- SHA-256 用于内容去重。
- 旧 `backend/data/documents.json` 仅作为已迁移的历史快照，不再参与运行时增删改查。
- 文件、旧 JSON、Chroma 和数据库备份都属于运行数据，不提交 Git。

## 7. 目标模块化架构

### 7.1 架构选择

项目继续采用**模块化单体**：一个 FastAPI 进程、一个 Vue 应用，但代码按业务能力隔离。现阶段不拆微服务，因为认证、知识库、RAG 和 Agent 仍共享用户、文档和会话数据；强行拆分会增加网络调用、分布式事务和部署成本，却不会直接改善作品质量。

目标不是一次性把目录搬得“像大厂”，而是保证每次新增功能都有一个明确归属和稳定调用方向。

### 7.2 后端目标目录

下面是演进方向，不要求一次性搬完；只有当前任务触及某模块时才迁移对应代码：

```text
backend/app/
|-- api/                              # 顶层路由聚合，不放业务逻辑
|-- core/                             # 配置、异常、日志、request_id、安全基础
|-- db/                               # Base、Session、Alembic 接入
|-- infrastructure/                   # 第三方系统适配器
|   |-- model_provider/               # 通义千问、Embedding
|   |-- vector_store/                 # Chroma；以后可替换 Qdrant/Milvus
|   |-- cache_lock/                   # Redis 限流与锁的底层操作
|   |-- file_storage/                 # 本地文件；以后可替换对象存储
|   `-- reranker/                     # 可选重排序实现
|-- modules/
|   |-- auth/                         # 用户、认证、角色与权限策略
|   |-- conversations/                # 会话、消息、来源和用户归属
|   |-- knowledge/                    # 文档登记、生命周期和公开权限
|   |-- rag/                          # 查询构造、检索、重排和回答生成
|   |-- agent/                        # 独立 Agent Runtime、工具和运行记录
|   `-- observability/                # 指标查询与管理端统计用例
|-- evaluation/                       # 离线评估集、Runner 和报告，不进用户会话
`-- main.py
```

一个业务模块按需要使用以下文件，不要求每个目录机械地凑齐：

```text
router.py       # HTTP/SSE 边界
schemas.py      # 对外输入输出
service.py      # 应用用例编排
ports.py        # 模块需要的稳定能力接口
repository.py   # 本模块 MySQL 持久化
models.py       # 本模块 SQLAlchemy 模型
policies.py     # 权限、预算、状态转换等纯业务规则
```

### 7.3 前端目标目录

```text
frontend/src/
|-- api/                              # HTTP/SSE 客户端与统一错误处理
|-- components/                       # 无页面业务的复用组件
|-- features/
|   |-- auth/
|   |-- chat/
|   |-- knowledge/
|   |-- admin/
|   `-- agent/
|-- router/
|-- stores/                            # 只保存确实跨页面共享的状态
`-- views/                             # 页面组合层，不写后端业务规则
```

Vue 页面只负责触发动作和展示状态。API 地址、Token、SSE 解析、错误映射分别集中管理；Agent 页面不得把工具选择规则写在前端。

### 7.4 固定依赖方向

```text
Router / CLI
-> Application Service
-> Domain Policy + Port
-> Repository / Infrastructure Adapter
-> MySQL / Chroma / Redis / DashScope / File System
```

规则：

1. Router 只做参数接收、身份依赖、调用服务和响应转换。
2. Service 只编排一个业务用例，不依赖 FastAPI `Request` 或 Vue 展示结构。
3. Repository 只访问本模块持有的 MySQL 数据，不调用模型、Redis 或 Chroma。
4. Infrastructure 只封装第三方系统，不决定用户权限、限流额度或 Agent 步骤上限。
5. Pydantic Schema 是接口契约，SQLAlchemy Model 和第三方 SDK 对象不跨模块传播。
6. 跨模块只能调用公开应用服务或小型 Port/Protocol，禁止导入对方 Router、Repository、Session 或私有对象。
7. `core` 和 `utils` 不承载文档、会话、RAG 或 Agent 业务规则。
8. 依赖由应用启动层或 FastAPI 依赖组装；业务代码不得到处创建全局客户端。

### 7.5 模块所有权

| 模块 | 持有的数据/规则 | 可以依赖 | 不允许负责 |
| --- | --- | --- | --- |
| `auth` | 用户、密码、JWT、角色 | 用户 Repository、安全适配器 | 文档、会话、模型调用 |
| `conversations` | 会话、消息、来源、用户归属 | 会话 Repository、RAG 对外用例 | 检索算法、Agent 工具选择 |
| `knowledge` | 文档登记、文件/向量生命周期、文档权限 | 文档 Repository、文件/向量/Embedding Port | 生成回答、修改用户角色 |
| `rag` | 查询构造、召回、重排、拒答、回答生成 | KnowledgeSearchPort、模型 Port | 写用户权限、管理上传文件 |
| `agent` | Run/Step 状态、工具调度、预算、审计 | 工具注册表和公开应用服务 | 直接访问数据库、Chroma、系统命令 |
| `observability` | 指标读取和统计视图 | 脱敏后的日志/指标 Port | 改变任何业务结果 |

### 7.6 关键共享端口

后续功能优先围绕这些小接口演进，名字可按代码风格调整，但职责不能合并成万能 Service：

- `KnowledgeSearchPort`：输入查询和过滤条件，输出带分数、来源和文档 ID 的候选片段。
- `DocumentReadPort`：按权限读取文档元数据或正文，供摘要和比较工具使用。
- `AnswerModelPort`：普通生成与流式生成，不暴露厂商 SDK。
- `RateLimitPort`：消费额度并返回是否允许与重试时间。
- `DistributedLockPort`：获取、续期和安全释放带所有权令牌的锁。
- `TelemetryPort`：记录阶段耗时、Token、错误和工具事件，不接收密钥或完整正文。

### 7.7 增量迁移和防回归

- 不进行一次性目录大搬家，不为了目录整齐改动稳定接口。
- 任务 6 只新增 Redis 保护组件，不顺手迁移 RAG 或会话目录。
- 任务 7 开始时先建立评估基线，再拆 `RetrievalService` 与 `AnswerService`；API 和 SSE 契约保持不变。
- 任务 8 增加可观测性时使用事件/Port 记录，不让日志代码决定业务分支。
- 任务 9 新建 `modules/agent`，通过公开 Port 复用知识检索和文档读取，不复制 RAG、文档或权限代码。
- 每次迁移前固定原行为测试，迁移后先跑模块测试，再跑完整回归。
- 新功能必须能通过配置或独立路由关闭；关闭后原 RAG 主链路仍可运行。

这样可以逐步获得成熟项目的模块化收益，同时避免“大重构一次改坏所有功能”。

## 8. 阶段五：登录、用户隔离与管理员管理 `[已完成]`

### 8.1 产品规则

- 邮箱和密码注册、登录。
- 每个用户只能查看、修改、删除自己的会话。
- 所有知识库文档都可被已登录用户检索。
- 新上传文档也进入公共知识库。
- 普通用户只能删除自己上传的文档。
- 系统预置文档不能由普通用户删除。
- 基础登录版本不做邮箱验证码、找回密码和 Refresh Token。

### 8.2 新增表与字段

`users` `[现状]`：

- `id`：UUID 主键。
- `email`：唯一、统一转小写。
- `display_name`：可选昵称。
- `password_hash`：只保存安全哈希。
- `is_active`：账号状态。
- `role`：只允许 `user` 和 `admin`；新注册固定为 `user`。
- `created_at`、`updated_at`。

`conversations` `[现状]`：

- `user_id`：外键，所有列表、详情、修改、删除和问答必须同时按该字段过滤。

`documents` `[现状]`，已替代 JSON 成为主登记源：

- `id`、`original_name`、`stored_name`、`content_hash`。
- `size_bytes`、`chunk_count`、`created_at`。
- `uploader_id`：系统文档可为空。
- `is_system`、`status`。
- `chunk_ids`：该文档在 Chroma 中的精确片段 ID 列表，用于一致删除和恢复。

### 8.3 认证接口 `[现状]`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/auth/register` | 创建用户并返回基本信息 |
| POST | `/api/v1/auth/login` | 校验密码并返回短期 JWT |
| GET | `/api/v1/auth/me` | 返回当前登录用户 |

密码使用 Argon2 哈希，JWT 使用短期 HS256 Bearer Token，默认 30 分钟过期，密钥只来自环境变量。登录失败统一提示“邮箱或密码错误”，不能泄漏邮箱是否存在；缺失、伪造、过期 Token 和已不存在的用户统一返回 401。

当前已完成 `users` 模型、Schema、Repository、注册/登录 Service、三个 HTTP 接口、JWT 签发校验和当前用户依赖。全部会话接口已按 `user_id` 隔离；文档上传、列表、删除也已接入认证，所有文档公共可见，删除由后端校验上传者且保护系统文档。Vue 已完成注册登录、Token 持久化、刷新时通过 `/auth/me` 恢复用户、退出、受保护路由、401 统一清理和返回原目标页；普通 Axios 与 SSE 请求都集中附带 Bearer Token。

前端登录数据流：

```text
访问 /chat 或 /knowledge
-> 路由守卫初始化本地登录状态
-> 无 Token 或 /auth/me 校验失败：跳转 /login 并保存原地址
-> 登录成功：保存短期 Token，读取当前用户，返回原地址
-> Axios/SSE 请求统一附带 Authorization
-> 任一受保护请求返回 401：清除 Token 和当前用户，回到登录页
-> 用户退出：清除本地凭据和当前用户状态
```

### 8.4 权限检查

| 操作 | 未登录 | 已登录用户 | 上传者 | 系统管理员 |
| --- | --- | --- | --- | --- |
| 检索公共文档 | 否 | 是 | 是 | 是 |
| 查看自己的会话 | 否 | 是 | 是 | 是 |
| 查看他人会话 | 否 | 否 | 否 | 按后续需求 |
| 上传公共文档 | 否 | 是 | 是 | 是 |
| 删除自己的上传 | 否 | 否 | 是 | 是 |
| 删除系统文档 | 否 | 否 | 否 | 是 |

所有权校验必须在后端 Service/Repository 查询条件中完成，不能只靠前端隐藏按钮。

### 8.5 数据迁移

1. 引入 Alembic，建立当前数据库基线。
2. `[已完成]` 备份现有会话表。
3. `[已完成]` 清空现有测试会话，再增加非空 `user_id` 约束。
4. `[已完成]` 使用空 `uploader_id`，把 36 份现有登记迁移为系统公共文档。
5. `[已完成]` 核对 Chroma 已有片段的 `document_id`，保留 37 个原片段，不重新调用 Embedding。
6. `[已完成]` 逐项对比 MySQL、旧 JSON、文件和 Chroma，确认无丢失、无重复。

数据库结构变化必须由 Alembic 完成，禁止只在本机手工修改表。

### 8.6 管理员与系统文档管理 `[已完成：任务 5.6]`

管理员能力属于认证和知识库模块，不建立跨模块的万能后台服务。

固定调用方向：

```text
普通文档路由 -> get_current_user -> UserDocumentService
管理员路由   -> require_admin    -> AdminDocumentService
                                      |
                                      v
                           DocumentLifecycleService
                                      |
                      Repository / FileStore / VectorStore
                                      |
                           MySQL / 文件 / Chroma
```

- 普通文档和系统文档必须复用同一套解析、哈希、切片、向量写入、删除快照和失败补偿能力。
- `UserDocumentService` 只实现普通用户上传、公开列表和删除自己的资料。
- `AdminDocumentService` 只实现系统文档新增、删除和替换，不接管会话、RAG 回答或普通用户资料。
- `DocumentService` 保留普通用户 API，用共享 `DocumentLifecycleService` 执行跨存储创建和删除；原有普通文档 API 契约未改变。

`users` 增加：

- `role`：第一版只允许 `user` 和 `admin`，新注册用户固定为 `user`。
- 管理员账号通过受控维护命令初始化，不开放“注册管理员”接口，也不允许前端提交角色字段。
- 数据库中的 `users.role` 是权限真相源。JWT 继续只保存用户 ID，不把角色作为长期授权依据；每次请求通过 `get_current_user` 读取当前数据库角色，使降权和停用立即生效。
- `/auth/me` 可以向前端返回角色用于导航展示，但前端角色只控制界面，不能代替后端授权。

后端使用统一的 `require_admin` 依赖。已实现管理员接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/admin/documents` | 新增系统文档 |
| DELETE | `/api/v1/admin/documents/{id}` | 删除系统文档 |
| PUT | `/api/v1/admin/documents/{id}/replace` | 用新文件整份替换系统文档 |

权限规则：

- 普通登录用户继续可以上传公开资料并删除自己的上传。
- 管理员额外拥有系统文档新增、删除和替换能力。
- 用户上传资料的审核机制属于后续可选增强，不在任务 5.6 中改变现有上传规则。

系统文档修改采用“整份替换”，不允许直接编辑磁盘 TXT：

```text
校验管理员身份
-> 用新文档 ID 暂存并解析新文件
-> 生成全新的片段 ID 和向量
-> 校验新文件、登记候选和向量完整
-> 保持旧版本可用，切换到新登记
-> 删除旧文件和旧向量
```

MySQL、文件系统和 Chroma 之间不存在一个真正的跨存储原子事务，因此不得把替换实现描述为数据库意义上的“原子提交”。任务 5.6 使用可补偿编排：新版本完全就绪前旧版本继续可用；切换或清理失败时删除新版本并恢复旧文件、旧登记和旧向量快照。最坏情况优先保留旧版本，禁止出现新旧版本同时丢失。

替换操作必须防止同一系统文档并发修改。第一版使用数据库行锁或明确的单操作保护；Redis 上线后再把跨进程锁接入统一锁适配器，不能在知识库业务代码中写死 Redis。

管理员前端使用独立 `/admin/knowledge` 路由和独立 API 模块。路由守卫可依据 `/auth/me` 的角色隐藏入口，但所有管理员接口仍必须执行 `require_admin`。普通 `KnowledgeView`、`documents.js` 和普通上传接口不得加入散落的管理员分支。

`backend/scripts/import_documents.py` 已改为通过受控的 `AdminDocumentService` 导入系统资料，要求显式 `--confirm`，并按内容哈希幂等跳过重复文件；不会直接写 MySQL 或 Chroma。

任务 5.6 明确禁止：

- 在多个路由或 Service 中重复编写 `if role == "admin"`；角色判断集中在认证依赖和知识库权限策略。
- 复制一套管理员专用的解析、切片、向量化和删除代码。
- 让认证模块导入知识库 Service，或让知识库模块修改用户角色。
- 让管理员接口直接使用 SQLAlchemy Session、Chroma 私有对象或磁盘路径。
- 通过修改 JWT 内容、前端 localStorage 或请求参数提升权限。
- 为了管理员功能修改会话表、RAG Prompt、聊天 SSE 协议或普通用户的数据隔离逻辑。

## 9. 阶段六：Redis 设计 `[完成]`

Redis 首先用于保护接口，不用于“为了简历而缓存所有东西”。

第一版用途：

- 注册和登录：按 IP 限制短时间尝试次数。
- 聊天：按用户限制分钟级请求次数，防止模型费用失控。
- 上传：普通用户按账号限制频率和并发；管理员系统文档上传跳过频率计数，但仍限制并发。
- 同一会话生成锁：避免重复点击同时生成两次。
- 幂等键：防止网络重试导致重复提交。

暂不做回答缓存。医疗问题即使文字相似，上下文和知识库版本也可能不同，直接复用回答容易造成错误。

Redis 不可用时的策略需要按功能区分：限流采用有界的本机保守兜底并记录告警，生成锁和幂等保护不能静默失效。Redis 只保存可重建的短期状态，用户、会话、文档和 Agent 运行记录仍以 MySQL 为真相源。

### 9.1 Redis 连接与故障基线 `[已完成：任务 6.1]`

- `Settings` 支持可选 `REDIS_URL`、连接超时和读写超时，真实地址使用 `SecretStr`，不会进入健康响应或日志。
- `RedisInfrastructure` 位于 Infrastructure 层，惰性创建 redis-py 客户端，集中封装单次 `PING`、故障连接丢弃和应用关闭释放。
- `/api/v1/health` 保持应用级 `status=ok`，并通过 `dependencies.redis.status` 区分：`ok` 表示连接正常，`disabled` 表示未配置，`degraded` 表示已配置但当前不可达。
- Redis 未配置或故障时，现有认证、会话、知识库和 RAG 主链路仍可启动。任务 6.1 尚未让任何业务依赖 Redis，因此这里采用 fail-open 并明确暴露降级状态。
- 每次健康检查最多尝试一次，默认连接与读写超时均为 0.5 秒，不做无限重试；日志只记录稳定消息和异常类型，不记录 URL、密码或第三方原始异常文本。
- 后续限流与生成锁必须分别定义策略：限流故障不能无声放开，生成锁故障必须阻止重复生成或返回明确错误。

### 9.2 限流边界 `[已完成：任务 6.2a-6.2c]`

限流由独立应用组件实现：

```text
Router 提供已校验的身份与客户端地址
-> RateLimitService 选择策略和业务键
-> RateLimitPort 原子消费额度
-> Redis Adapter 执行计数与 TTL
```

- Router 不直接执行 Redis 命令。
- 业务键不包含邮箱、Token、问题正文或其他敏感信息；用户 ID/IP 需要稳定归一化。
- 默认不信任任意 `X-Forwarded-For`。只有配置受信代理后才解析转发地址。
- 认证限流按直接 IP，聊天和上传按用户 ID；它们使用不同前缀、窗口和额度。
- 超限统一返回 429、业务错误码、`request_id` 和 `Retry-After`。
- Redis 不可用时，认证接口使用有容量上限和自动过期的本机兜底；多实例部署时兜底只保证单实例安全，健康状态和日志必须明确降级。

任务 6.2a 的当前实现：

- 注册默认每个 IP 在 600 秒内最多 5 次，登录默认每个 IP 在 300 秒内最多 10 次；窗口和上限均可通过环境配置调整。
- IP 先规范化再计算 SHA-256 摘要，Redis 键只保存业务前缀和摘要，不保存原始 IP、邮箱或密码。
- `RedisInfrastructure.consume` 使用单条 Lua 脚本原子执行 `INCR`、首次 `EXPIRE` 和 `TTL`；认证应用服务只依赖 `RateLimitPort`，不接触 redis-py。
- 默认只使用直接连接 IP。仅当直接连接地址出现在 `TRUSTED_PROXY_IPS` 时，才采用 `X-Forwarded-For` 的首个合法地址。
- Redis 未配置或命令失败时切换到进程内兜底；兜底最多保存 `AUTH_RATE_LIMIT_FALLBACK_MAX_KEYS` 个自动过期键，容量耗尽时保守拒绝新键，不静默放开。
- 注册与登录超限均返回 `AUTH_RATE_LIMITED`、429、`request_id` 和 `Retry-After`，不根据邮箱是否存在改变限流响应。
- 任务 6.2a 当时没有修改聊天、上传、会话生成、SSE、RAG 或文档生命周期；后续能力继续按拆分任务接入。

任务 6.2b 的当前实现：

- `/chat`、`/chat/stream`、会话非流式问答和会话 SSE 问答统一要求 Bearer Token，并共享同一个按用户额度；默认每个用户 60 秒最多 10 次，可通过环境配置调整。
- 通用 `RateLimitService` 负责主体摘要、Redis/本机故障切换和恢复日志；认证与聊天策略只选择各自命名空间、窗口、上限和业务错误。
- 用户 ID 先计算 SHA-256 摘要，键中不包含用户 ID、Token、邮箱、问题、会话 ID 或正文；不同用户额度互不影响。
- 四个入口均在检索、模型调用和创建 `StreamingResponse` 前消费额度。超限返回 JSON HTTP 429、`CHAT_RATE_LIMITED`、`request_id` 与 `Retry-After`，不会返回 200 后再发送 SSE 错误事件。
- Redis 未配置或命令失败时复用有容量上限、自动过期且容量耗尽时保守拒绝的本机兜底；多实例部署时只保证单实例额度。
- 当前没有修改上传、文档生命周期、会话生成锁、幂等、Prompt、检索算法或模型参数。

任务 6.2c 的当前实现：

- 普通文档上传默认每个用户 3600 秒最多 5 次，同时最多处理 1 个上传。管理员新增和整份替换系统文档使用独立的不可变保护策略：跳过频率计数，但继续复用同一个并发租约机制，同一管理员同时最多处理 1 个上传。
- 管理员策略只由 `AdminDocumentService` 选择；路由不判断限流规则，Redis 适配器和文档生命周期不感知角色，避免权限、保护和存储职责耦合。
- 管理员“不限次数”不绕过 10 MB 文件上限、扩展名校验、SHA-256 去重、生命周期事务和失败补偿。
- 频率键使用 `upload:frequency`，并发占位键使用 `upload:concurrency`；两者都只包含用户 ID 的 SHA-256 摘要，不包含邮箱、Token、文件名或正文。
- 频率和并发检查均发生在项目文件落盘、解析、Embedding、Chroma 与 MySQL 写入前；被拒绝时关闭上传句柄且不进入 `DocumentLifecycleService`。
- Redis 使用 Lua 和有序集合原子清理过期占位、检查容量并写入随机所有权令牌；释放使用 `ZREM` 只删除匹配令牌。占位默认 TTL 600 秒，进程崩溃后可自动回收。
- Redis 不可用时复用有容量上限的进程内频率与并发保护；多实例时只保证单实例安全并记录降级。容量耗尽时保守拒绝，不静默放开昂贵上传。
- 成功、业务异常和客户端取消都在 `finally` 中释放实际获取占位的后端；释放状态不明确时保留 TTL 作为最终保护。
- 受控批量导入脚本不经过公开上传保护，继续要求显式 `--confirm`，避免把维护批次误计为某个网页账号的额度。
- 当前没有修改共享文档生命周期、聊天、Prompt、检索算法、会话生成锁或幂等协议。

### 9.3 生成锁与幂等边界 `[任务 6.3a-6.3b 已完成]`

任务 6.3a 的当前实现：

- 会话非流式和 SSE 问答在消息保存、检索和模型调用前，以“用户 ID + 会话 ID”的 SHA-256 摘要获取独立 `lock:generation` 锁；普通无会话问答不使用该锁。
- Redis 通过 `SET NX EX` 原子获取锁，所有权令牌为每次请求随机生成，默认 TTL 600 秒；释放使用 Lua 原子比较 `GET` 后 `DEL`，旧请求不能删除后来请求的锁。
- 锁已占用时在 SSE 响应开始前返回 JSON 409、`CONVERSATION_GENERATION_IN_PROGRESS` 和 `request_id`；Redis 未配置、命令失败或状态不明确时返回 JSON 503、`GENERATION_LOCK_UNAVAILABLE`，不会保存消息、检索或调用模型。
- 非流式成功和失败均在 `finally` 释放；SSE 完成、模型失败、主动停止、客户端断开和生成器关闭也会释放。主动停止不再只依赖客户端断开：`StreamCancellationService` 以用户、会话和客户端请求标识摘要登记当前进程任务，停止接口设置取消信号；会话流使用 `DashScopeAsyncChatModel` 的原生异步 HTTP SSE，等待下一块时每 50ms 检查取消信号，命中后取消本地读取任务并关闭底层响应流，而不是等待模型自然返回下一块。随后生成器保存部分内容为 `stopped`、清理幂等状态、释放锁并发送 `stopped` 事件，前端收到流结束后才恢复发送。释放状态不明确时不误删，保留有限 TTL 最终回收。
- 当前本机 `.env` 已配置仅限回环地址的 `REDIS_URL`，健康状态为 `ok`；带会话问答可以使用真实生成锁，Redis 停止时仍按上述策略明确返回 503。

任务 6.3b 的当前实现：

- 会话非流式与 SSE 问答要求 `Idempotency-Key` 请求头，长度 1-128，只允许字母、数字、点、下划线、冒号和连字符；Vue 每次点击发送生成一个 UUID，并在该次请求生命周期内保持不变。
- 幂等键由用户、接口和客户端请求 ID 的 SHA-256 摘要组成，请求指纹绑定会话、清理后的问题和 `top_k`；Redis 键不暴露用户 ID、请求 ID 或问题正文，相同 Key 改变请求内容返回 409 `IDEMPOTENCY_KEY_REUSED`。
- Redis Lua 原子创建 `in_progress` 哈希记录，默认 600 秒；并发重复返回 409 `IDEMPOTENCY_REQUEST_IN_PROGRESS`。成功后只保存 request/conversation/user-message/assistant-message ID，默认保留 86400 秒，不缓存完整医疗回答。
- 已完成的普通重复请求从 MySQL 恢复原回答、引用与资源 ID；SSE 重复请求从 MySQL 产生一次 token、sources 和 done 的稳定回放，不再次保存消息、检索或调用模型。
- 模型失败、主动停止和生成器关闭会按请求指纹清理进行中记录，允许同 Key 重试；回答已经写入 MySQL但结果登记状态不明确时保留有界进行中 TTL，避免立即重复产生模型费用。
- Redis 未配置或幂等命令失败时在消息保存、检索和模型调用前返回 503 `IDEMPOTENCY_UNAVAILABLE`。当前本机 Redis 已可用，可进行真实带会话问答与重复请求验收。

### 9.4 故障矩阵与阶段冻结 `[任务 6.4a-6.4b 已完成]`

任务 6.4a 的当前实现：

| Redis 场景 | 限流与上传并发 | 生成锁与幂等 | 应用健康状态 |
| --- | --- | --- | --- |
| 未配置 | 有界本机兜底 | fail-closed，返回 503 | 应用 `ok`，Redis `disabled` |
| 连接或命令失败 | 有界本机兜底 | fail-closed，返回 503 | 应用 `ok`，Redis `degraded` 或具体保护为 `unavailable` |
| 锁释放所有权不符、幂等完成登记不符 | 不适用 | 状态不明确，保持 TTL 并标记 `unavailable` | 应用仍为 `ok` |
| 后续命令成功 | 恢复 Redis 模式 | 恢复 `available` | 记录一次恢复迁移 |

- `ProtectionObservability` 是应用内共享状态登记器；限流和上传并发策略为 `local_fallback`，生成锁和幂等策略为 `fail_closed`。
- `/api/v1/health` 在原有 `dependencies.redis.status` 外增加 `dependencies.protections`，按功能返回 `policy`、`mode`、成功/失败/恢复计数及 `last_error_type`。单个保护能力降级不会把应用误报成整体宕机。
- 运行日志只在正常与降级状态发生迁移时写一次结构化记录；重复失败只累加计数，不重复刷告警。日志和健康响应不记录 Redis URL、Token、邮箱、问题、回答、文件名或文档正文。
- 观测组件由应用入口创建并注入现有限流、上传并发、生成锁与幂等服务；Router 和业务服务仍不直接执行 Redis 命令，原 429/409/503 契约不变。
- 任务 6.4a 没有修改 Vue 页面、数据库、RAG、上传生命周期、Agent 或 Docker，也没有调用模型。

任务 6.4b 已实现前端稳定提示与可取消的后端模型流。真实 HTTP 已证明首次生成、幂等恢复和两类 409 冲突；真实页面已证明长回答生成中停止后约 2.5 秒恢复发送，并可立即在同一会话再次提问且无 409 冲突。30 秒阻塞模型替身在 0.5 秒验收上限内被取消，完整回归通过，`RAG v1.1` 已冻结。

## 10. 阶段七：RAG 检索优化 `[目标]`

当前 `RagService` 同时负责检索和回答生成。后续保持外部聊天 API 不变，内部逐步拆为：

```text
QueryBuilder       # 结合历史生成检索问题
RetrievalService   # 返回带分数的候选片段
RerankService      # 可替换的重排序实现
AnswerService      # Prompt 和模型流式生成
RagApplicationService # 编排以上步骤
```

演进顺序必须先量化基线，再改算法：

1. 建立 30-50 个固定问题，覆盖单文档命中、多文档命中、连续追问和知识不足拒答。
2. 保存当前向量检索的来源命中率、拒答准确率、延迟和费用，形成不可篡改的基线报告。
3. 把检索、重排和回答拆为稳定接口，不改变前端和会话持久化。
4. 为片段补充科室、主题、文档类型、知识库版本等可过滤元数据。
5. 增加最低相关度和明确拒答策略。
6. 融合关键词检索与向量检索，再通过统一接口接入可关闭的 Reranker。
7. 对每项改动分别运行同一评估集，只有指标改善且成本可接受时才保留。

任何“效果提升”都必须由评估结果证明，不能只凭页面上某一次回答判断。评估集、运行结果和线上会话分开保存，测试问题不能污染用户历史。

## 11. 阶段八：可观测性 `[目标]`

结构化日志至少包含：

- `request_id`、路由、用户 ID（脱敏或内部 ID）。
- 状态码、总耗时、检索耗时、模型耗时。
- 召回片段数量和文档 ID，不记录文档全文。
- 模型名、输入/输出 Token 数、错误类型。
- 用户停止、超时、限流和工具失败事件。

默认不记录完整问题、回答、Prompt、密码、Token、API Key 或医学文档正文。

评估数据与线上会话分开保存，避免把人工测试结果混进用户记录。业务模块通过 `TelemetryPort` 提交结构化事件；日志组件只能观察，不能改变权限、检索结果或 Agent 决策。

第一版可观测性不必引入庞大平台，先完成：

1. JSON 结构化日志和统一字段。
2. 请求、检索、模型、工具四类阶段耗时。
3. 模型 Token 和估算费用。
4. 管理员只读统计接口或简单页面。
5. 限流、Redis 降级、失败和中止计数。

以后接入 OpenTelemetry、Prometheus 或 Grafana 时，只替换适配器，不改业务 Service。

## 12. 阶段九：Agent 设计 `[目标]`

Agent 是独立的“医学资料整理”能力，不替换现有稳定的 RAG 问答，也不把普通聊天改造成不可控循环。

### 12.1 两条互不影响的产品链路

```text
普通知识问答
-> ConversationChatService
-> RagApplicationService
-> 检索一次 + 回答一次

复杂资料任务
-> AgentApplicationService
-> Agent Runtime 状态机
-> Tool Registry
-> 一个或多个受控工具
-> 最终结果与执行记录
```

Agent 模块只依赖工具契约，不知道 Chroma、SQLAlchemy、redis-py 或 DashScope SDK 的具体对象。普通 RAG 可以作为工具背后的能力，但不能反向依赖 Agent。

### 12.2 第一版工具

第一版可用工具：

- `search_knowledge`：调用 `KnowledgeSearchPort` 检索公共知识库，返回结构化片段与来源。
- `get_document_info`：读取用户有权查看的文档元数据，帮助模型消除同名歧义。
- `summarize_document`：按文档 ID 获取受控正文并生成摘要。
- `generate_learning_report`：基于已获得的检索/摘要结果生成带引用的学习报告。

多文档比较可以在以上工具稳定后作为下一任务增加，不在第一个 Agent 任务中一次做完。

### 12.3 Agent Runtime 与状态

调用链：

```text
用户提出任务
-> 创建 agent_run，状态 pending
-> Runtime 切换为 running，并让模型选择白名单工具
-> Tool Registry 校验工具名和参数
-> Tool 调用公开 Application Service/Port
-> 保存工具状态、耗时和脱敏结果摘要
-> Runtime 决定继续、完成、失败或停止
-> 保存最终回答、引用和运行状态
```

`agent_runs` 计划保存：用户、任务、状态、步骤数、模型、预算、最终结果、错误类型和时间字段。`agent_steps` 计划保存：顺序、工具名、脱敏参数摘要、结果摘要、状态和耗时。必要时用 `agent_artifacts` 保存学习报告等产物。数据库不保存模型隐藏推理过程或完整 Chain-of-Thought，只保存用户可理解的工具事件和审计信息。

状态第一版限定为：`pending`、`running`、`completed`、`failed`、`stopped`。需要人工确认的高风险工具出现后，再引入 `waiting_confirmation`，不要提前增加无用状态。

### 12.4 API、SSE 与前端边界

建议使用独立路径：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/v1/agent/runs` | 创建资料整理任务 |
| GET | `/api/v1/agent/runs` | 查看当前用户运行历史 |
| GET | `/api/v1/agent/runs/{id}` | 查看运行、步骤和产物 |
| POST | `/api/v1/agent/runs/{id}/stop` | 请求停止运行 |
| POST | `/api/v1/agent/runs/{id}/stream` | 以 SSE 执行并返回事件 |

Agent SSE 事件使用独立契约：`run_started`、`tool_started`、`tool_completed`、`token`、`run_completed`、`error`。事件只展示“正在检索哪类资料、工具是否成功、最终输出”等可审计信息，不输出模型私有推理。

前端新增独立 `/agent` 页面和 `api/agent.js`，普通 `ChatView`、`conversations.js` 和现有聊天 SSE 解析器保持不变。

### 12.5 安全与成本约束

- 使用 LangGraph 的显式状态图或同类可观察编排，不写无限 while 循环。
- 工具只能调用公开 Service，禁止直接连接 MySQL、Chroma 或操作系统。
- 第一版最多 5 个步骤；每个工具有超时，整次运行有 Token/费用预算和主动停止。
- 工具参数必须由 Pydantic Schema 校验，工具异常转换为稳定结果，不把 Traceback 重新喂给模型。
- 第一版不开放网页搜索、任意 Python/SQL、系统命令、自动诊断或处方能力。
- Agent 使用当前登录用户身份执行，运行历史按用户隔离；管理员身份不能绕过工具自身的数据权限。
- Agent 故障、依赖超时或功能开关关闭时，普通 `/chat` 和 `/conversations/*/chat` 仍正常运行。

### 12.6 暂缓能力

- 多 Agent 协作。
- 可视化拖拽工作流编辑器。
- 用户自定义任意工具或插件市场。
- 浏览器/代码执行沙箱。
- 长时间后台任务队列与跨机器调度。

这些是成熟平台为通用场景提供的能力，当前项目只有出现真实需求后再引入。

## 13. 统一接口与错误规范

普通 JSON 错误建议保持：

```json
{
  "code": "RESOURCE_NOT_FOUND",
  "message": "请求的资源不存在",
  "request_id": "uuid"
}
```

普通聊天 SSE 事件保持：

- `token`：新增文本。
- `sources`：引用来源数组。
- `done`：持久化完成后的 ID 和免责声明。
- `error`：安全错误码、提示和 request_id。

Agent 使用 12.4 节的独立事件，不允许把 `tool_started` 等事件塞入普通聊天解析器。

后端不向前端返回 Traceback、SQL、服务器路径、密钥或第三方原始异常。

## 14. 配置与秘密

现有配置：

- `DASHSCOPE_API_KEY`
- `CHAT_MODEL_NAME`
- `EMBEDDING_MODEL_NAME`
- `CHROMA_PERSIST_DIR`
- `CHROMA_COLLECTION_NAME`
- `UPLOAD_DIR`
- `DOCUMENT_REGISTRY_PATH`
- `DATABASE_URL`
- 可选 `REDIS_URL`、`REDIS_CONNECT_TIMEOUT_SECONDS`、`REDIS_SOCKET_TIMEOUT_SECONDS`
- `JWT_SECRET_KEY`、`JWT_ALGORITHM`、`JWT_EXPIRE_MINUTES`
- `CORS_ORIGINS`
- 历史轮数、字符上限、切片参数和上传大小限制

后续新增：

- 认证、聊天、上传限流参数和受信代理配置已加入。
- 生成锁 TTL、幂等进行中 TTL 和结果有效期已加入。
- 日志级别、指标和评估配置。
- Agent 功能开关、最大步骤、单工具超时和 Token/费用预算。

真实值只放在本地 `.env` 或部署平台秘密配置中，`.env`、数据库备份、上传文件、Chroma 和日志不得提交 Git。

## 15. 测试策略

测试按风险分层：

1. Service 单元测试：假模型、假 Embedding、临时数据库。
2. API 测试：状态码、权限、参数和安全错误结构。
3. 数据一致性测试：MySQL、文件和 Chroma 的组合写入/删除。
4. 前端组件测试：状态切换、流式追加、删除确认和登录失效。
5. SSE 字节分片测试：中文跨网络分片仍能正确解析。
6. 真实浏览器冒烟：关键页面能看到预期变化且控制台无错误。
7. 迁移测试：升级和必要的回滚路径都可执行。
8. RAG 评估：固定问题集对比质量、耗时和成本。
9. 架构边界测试：Agent 工具不直接导入 Repository/第三方 SDK，普通聊天不依赖 Agent。
10. 故障注入：Redis、Chroma、模型和工具超时后，错误状态与补偿符合约定。

涉及外部模型的自动化测试默认使用假实现，避免重复付费和不稳定结果。

## 16. 部署架构 `[现状 + 待完善]`

为满足求职展示，项目已提前建立 Docker 云端部署基线。部署不改变模块化单体的代码边界，本地仍是唯一开发工作区，服务器只运行经过测试的版本；不能一边修改数据库和 Agent，一边直接编辑线上唯一实例。

```text
Nginx
|-- /             -> Vue 静态文件
`-- /api          -> FastAPI

Docker Compose
|-- backend
|-- mysql
|-- redis
`-- nginx
```

Chroma、上传文件、MySQL 和 Redis 使用独立持久卷。2 核 2G 服务器只运行应用服务，模型和 Embedding 继续调用云 API；容器需要设置内存和日志大小上限。

上线后继续开发的推荐方式：本地开发和测试通过后构建版本镜像，再更新服务器；线上数据卷不随代码发布覆盖。高风险数据库迁移先备份，再单独执行，失败时回退应用版本。

当前阿里云基线使用 Ubuntu 22.04 和 HTTP 端口 80，只开放 Nginx；FastAPI、MySQL 和 Redis 均不映射公网端口。真实秘密由服务器本地 `deploy/.env` 注入。HTTPS、自动备份、重启恢复和完整业务验收仍是待完成项，具体操作见 `docs/deployment.md`。

## 17. 架构变更规则

发生以下变化时必须更新本文档：

- 新增或删除模块。
- API 路径、请求、响应或 SSE 事件改变。
- 数据表或权限规则改变。
- 外部系统依赖改变。
- RAG 检索、Prompt 或 Agent 工具边界改变。
- 部署拓扑改变。

开发者完成任务后还必须同步更新 `docs/handoff.md` 和 `docs/development-roadmap.md`，保证新账号、新窗口或新开发者不依赖聊天记录也能继续工作。
