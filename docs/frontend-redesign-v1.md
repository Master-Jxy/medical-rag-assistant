# 企业级前端重设计 v1

> 状态：实施基线
> 范围：仅重设计 Vue 3 前端，不改变 FastAPI API、权限、数据库、SSE、RAG、Agent、额度与记忆语义。
> 目标：把现有功能完整但视觉分散的页面，统一为适合医疗资料运营、知识问答和系统治理的企业应用。

## 1. 设计结论

本轮不是给旧页面换一层颜色，而是统一四件事：

1. 信息架构：用户工作区、知识工作区、管理中台和系统管理有清晰分组。
2. 设计系统：尺寸、颜色、文字、图标、按钮、状态、表格和反馈使用统一规则。
3. 业务组件：聊天、来源、任务时间线、文档表、筛选栏和指标面板可以复用。
4. 响应式：1440、1280、900、390 宽度都能完成主要操作，不靠缩小字体硬塞。

企业感来自稳定的布局、明确的状态、可扫描的数据和完整交互，不使用大面积渐变、装饰光球、巨型营销标题或多层卡片。

## 2. 对标产品与许可边界

| 参考产品 | 借鉴内容 | 许可与使用边界 |
|---|---|---|
| Open WebUI | 会话侧栏、聊天画布、底部输入器、空会话引导、消息工具区 | 当前仓库使用带品牌限制的 Open WebUI License；只借鉴通用布局和交互规律，不复制当前受限制源码、品牌、图标或一比一视觉 |
| Codex | 用户消息、公开执行过程、工具调用循环、完成后折叠、最终回答与过程分离 | 只借鉴已公开可见的交互思想；不伪造品牌，不展示隐藏推理、Prompt 或 scratchpad |
| Dify | 知识库信息架构、资料状态、筛选与操作组织、Agent/RAG 工作区分离 | modified Apache 2.0，前端品牌和外观存在额外限制；只借鉴业务结构，不复制 Dify 前端源码或专利化外观 |
| Langfuse | 用量、质量、调用链、时间筛选、指标卡与明细表 | 核心非 `ee/` 代码为 MIT；本项目优先借鉴其可观测性信息架构，不复制企业版目录 |
| Supabase Dashboard | 紧凑侧栏、设置页、用户表、标签页、详情抽屉和低装饰数据面板 | Apache 2.0；可以借鉴结构与实现思想，保留必要版权声明后才可复制实质代码。本轮以重新实现为主 |
| Grafana | 时间范围、状态颜色、图表与表格的扫描顺序 | AGPL-3.0；仅借鉴通用可观测性模式，不复制源码 |
| Plane | 工作区导航、列表密度、操作反馈 | AGPL-3.0；仅借鉴通用模式，不复制源码 |
| vue-pure-admin | Vue 3 + Element Plus 的响应式后台工程技巧 | MIT；可参考组件组织，但不整体套模板，避免引入与业务无关的框架体积 |
| v3-admin-vite | Vue 3 + Element Plus 表格、筛选和移动端实现 | MIT；可参考实现方式，保持本项目 JavaScript 技术栈和已有 API 层 |

参考地址：

- https://github.com/open-webui/open-webui
- https://github.com/langgenius/dify
- https://github.com/langfuse/langfuse
- https://github.com/supabase/supabase
- https://github.com/grafana/grafana
- https://github.com/makeplane/plane
- https://github.com/pure-admin/vue-pure-admin
- https://github.com/un-pany/v3-admin-vite

禁止事项：

- 不复制商标、产品名、logo、专有插图和独有文案。
- 不直接搬运 Dify 或当前 Open WebUI 受限制的前端源码。
- 不从 AGPL 项目复制组件代码到当前仓库。
- 不制造看起来像官方产品的欺骗性一比一复刻。
- 不把“参考某产品”写成“使用该产品源码”。

## 3. 产品结构

### 3.1 全局壳层

桌面采用 `240px` 固定侧栏、`56px` 顶栏和弹性内容区：

```text
┌──────────────┬──────────────────────────────────────────────┐
│ 品牌/工作区   │ 面包屑                           状态/账号菜单 │
│              ├──────────────────────────────────────────────┤
│ 用户导航      │                                              │
│ 知识导航      │                 页面内容                     │
│ 管理导航      │                                              │
│              │                                              │
│ 账号与版本     │                                              │
└──────────────┴──────────────────────────────────────────────┘
```

- 侧栏宽度：展开 `240px`，小桌面可收起为 `68px`，`900px` 以下改为抽屉。
- 顶栏高度：`56px`，只放面包屑、运行状态、帮助入口和账号菜单。
- 普通内容最大宽度：`1280px`；聊天页面允许占满可用高度与宽度。
- 页面水平留白：桌面 `24px`，平板 `20px`，手机 `14px`。
- 页面标题：`22px/30px`；面板标题 `15px/22px`；正文 `14px/22px`。
- 侧栏以图标 + 文字显示；使用当前官方 Vue 包 `@lucide/vue`，不手绘 SVG。

导航分组：

```text
工作空间
  工作台
  知识问答
  资料 Agent

知识空间
  公共知识库
  我的资料

账户
  个人中心

运营管理（admin / super_admin）
  管理概览
  审核中心
  知识资产
  任务中心
  质量分析
  运行监控
  用量管理
  审计记录
  系统资料

系统管理（super_admin）
  用户与角色
```

### 3.2 页面壳层

所有业务页复用：

- `PageHeader`：面包屑、标题、短说明、右侧主操作。
- `MetricStrip`：紧凑指标，不做大号宣传数字。
- `FilterBar`：搜索、状态、时间、刷新和导出。
- `DataTable`：固定表头、空状态、加载、错误、局部横向滚动。
- `StatusBadge`：文本 + 语义色，不只依赖颜色。
- `DetailDrawer`：记录详情、来源、审核与追踪。
- `ConfirmDialog`：删除、驳回、调整额度等高影响操作。

不得继续使用 `window.prompt` 或 `window.confirm` 处理业务表单；改为 Element Plus `Dialog`、`Drawer`、`Form`，但不改变接口参数。

## 4. 视觉系统

### 4.1 色彩

```css
--bg-canvas: #f4f6f8;
--bg-surface: #ffffff;
--bg-subtle: #f8fafb;
--bg-sidebar: #18211f;
--text-strong: #17201e;
--text-default: #34413e;
--text-muted: #6b7774;
--border-default: #dce3e1;
--border-strong: #c9d3d0;
--brand: #167a68;
--brand-hover: #116858;
--action: #2563eb;
--success: #198754;
--warning: #b7791f;
--danger: #c2413a;
--info: #3973a8;
```

说明：品牌绿只用于品牌、选中态和关键确认；蓝色用于通用操作；黄色、红色和信息蓝用于业务状态，避免整站只有青绿色。

### 4.2 尺寸与阴影

- 圆角：输入与按钮 `6px`，面板 `8px`，状态标签 `999px`。
- 面板阴影：默认不用；悬浮菜单、抽屉、对话框使用轻阴影。
- 图标按钮：`32x32px` 或 `36x36px`，必须有 `aria-label` 和 tooltip。
- 普通按钮高度：`36px`；紧凑表格按钮 `30px`。
- 表格行高：`48-52px`；指标条高度 `88-104px`。
- 字间距固定为 `0`，不使用负字距和随视口缩放字体。

### 4.3 状态反馈

每个异步区域必须提供：

- 首次加载：骨架屏或明确加载行。
- 局部刷新：保留旧数据，刷新按钮显示 loading。
- 空状态：说明为什么为空，并只给一个最相关操作。
- 错误：短错误摘要、重试按钮；请求标识放在可展开详情。
- 成功：使用 toast 或局部状态条，不永久占据页面顶部。
- 无权限：明确角色边界，不能只显示空白。
- 降级：如 usage 未知、模型计量不可用，需要显示“未知”原因。

## 5. 逐路由对标与改造

| 路由 | 核心对标 | 重设计结果 |
|---|---|---|
| `/` | Supabase 产品控制台入口 | 收敛巨型标题，展示系统状态、能力摘要和登录入口；首屏仍能看见真实系统界面信号 |
| `/login`、`/password-reset` | Supabase Auth | 居中窄表单 + 左侧或顶部品牌说明；验证码、密码强度、失败与冷却状态清晰 |
| `/dashboard` | Supabase / Langfuse | 指标条、最近资料、最近会话和快捷操作组成工作台；减少空白 |
| `/chat` | Open WebUI + 现有 RAG | 左侧会话 `260px`，主消息区弹性；消息正文最大 `820px`；输入器固定底部；来源折叠、usage、反馈和停止生成全部保留 |
| `/agent` | Codex + Open WebUI | 与 RAG 使用同一聊天视觉；助手消息上方显示公开执行过程，运行时展开、结束后折叠；工具步骤、来源和产物按消息归属 |
| `/knowledge` | Dify Dataset + Supabase Table | 顶部搜索/筛选，文档表为主；上传使用简洁拖放区或对话框；详情进入抽屉 |
| `/my-documents` | Dify Dataset | 我的提交、审核状态、失败原因和撤回操作形成清晰数据表；状态筛选保留 |
| `/profile` | Supabase Settings | 账号、长期记忆、用量与额度改为页内标签；移动端标签可横向滚动，不嵌套卡片 |
| `/admin` | Langfuse Dashboard | 关键指标、待处理事项、系统健康和快捷入口；图表只承载已有真实数据 |
| `/admin/reviews` | Dify Review Queue | 队列表格 + 右侧审核抽屉；审核原因使用表单，不用 prompt |
| `/admin/knowledge-assets` | Dify Knowledge | 知识资产筛选表、版本与来源详情抽屉，批量操作只在已有 API 支持时显示 |
| `/admin/jobs` | Supabase Jobs / Langfuse Traces | 任务状态、耗时、错误摘要；失败任务详情可展开，重试有确认 |
| `/admin/audit` | Supabase Logs | 时间/操作者/动作筛选，紧凑日志表，详情抽屉显示脱敏元数据 |
| `/admin/knowledge` | Dify Dataset | 管理员上传、系统资料维护和发布状态合并成清晰工作流 |
| `/admin/telemetry` | Langfuse / Grafana | 时间范围、核心健康指标、趋势与明细；没有真实序列时不伪造图表 |
| `/admin/quality` | Langfuse Scores | 质量指标、问题分类、反馈明细和评估入口；保持现有数据语义 |
| `/admin/usage` | Langfuse Usage | token、费用、请求和用户分布；actual/unknown/not_applicable 语义明确 |
| `/super-admin/users` | Supabase Auth Users | 用户表、角色、状态和额度；角色与额度调整放入受审计对话框 |

## 6. 聊天工作区契约

### 6.1 RAG

```text
会话列表 260px | 消息画布 minmax(0, 1fr)
```

- 会话列表有新建、搜索占位、标题、消息数、当前态和删除菜单。
- 消息区按数据库顺序渲染；用户消息靠右但宽度受限，助手消息使用无大气泡或浅表面。
- 来源使用与回答同宽的折叠区；展开后是文件名、页码、摘要和来源操作。
- 输入器贴近底部，宽度与消息正文一致；发送用图标按钮，停止生成清晰可见。
- 流式 token 不改变消息容器宽度，不造成页面跳动。
- 保留 `data-testid`、SSE 回调、幂等键、停止、刷新恢复、反馈、usage 和自动聚焦契约。

### 6.2 Agent

- Agent 与 RAG 共用 `ConversationSidebar`、`ChatComposer`、`MessageActions` 和 `SourceDisclosure` 的视觉语言。
- 公开执行过程显示计划、工具名、状态、简短结果和错误摘要。
- 过程结构是“模型决策 -> 工具调用 -> 观察结果 -> 下一决策”的公开事件序列；不显示模型隐藏思维。
- 运行中默认展开；完成/失败/停止后默认折叠，并显示“完成 · N 次工具调用 · X 秒”。
- 最终回答永远在执行过程之后，并作为助手消息正文显示。
- 产物只在真实存在时显示下载入口，不保留永久右侧栏。
- 保留 sequence 排序、REST/SSE 幂等归并、停止、重试、来源、artifact 和 usage 契约。

## 7. 共享组件计划

新增目录：

```text
frontend/src/components/app/
  AppBreadcrumbs.vue
  AppIconButton.vue
  AppPageHeader.vue
  AppStatusBadge.vue
  AppMetric.vue
  AppEmptyState.vue
  AppErrorState.vue
  AppSection.vue

frontend/src/components/data/
  DataToolbar.vue
  DataTableShell.vue
  DetailDrawer.vue
  ConfirmActionDialog.vue

frontend/src/components/chat/
  ConversationSidebar.vue
  ChatMessage.vue
  ChatComposer.vue
  MessageActions.vue
  SourceDisclosure.vue
```

原则：

- 共享组件只负责展示和通用交互，不调用业务 API。
- View 负责组合 Feature；API 调用、SSE reducer 和权限判断继续留在现有模块边界。
- 不为了美化引入 Pinia、Tailwind、另一套 UI 框架或图表库。
- 图表优先使用现有 CSS/SVG 实现；确实需要交互图表时再单独评估 ECharts。

## 8. 文件所有权与并行开发

并行任务不能同时编辑同一文件：

### 任务 A：设计系统与壳层

拥有：

- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/src/main.js`
- `frontend/src/App.vue`
- `frontend/src/style.css`
- `frontend/src/components/app/**`
- `frontend/src/components/data/**`

### 任务 B：用户端与认证

拥有：

- `HomeView.vue`
- `LoginView.vue`
- `PasswordResetView.vue`
- `DashboardView.vue`
- `KnowledgeView.vue`
- `MyDocumentsView.vue`
- `ProfileView.vue`
- `features/profile/**`

### 任务 C：RAG 与 Agent

拥有：

- `ChatView.vue`
- `AgentView.vue`
- `features/agent/**`
- `components/chat/**`
- `MarkdownContent.vue`
- `UsageMeta.vue`

### 任务 D：管理中台

拥有：

- 所有 `Admin*View.vue`
- `SuperAdminUsersView.vue`

任务 A 先落地公共 token 和壳层；B、C、D 再基于稳定公共样式开发。任何任务不得修改后端和 API 契约。

## 9. 响应式规则

### 1440

- 侧栏 `240px`，内容区完整显示。
- 聊天会话栏 `260px`，消息正文最大 `820px`。
- 管理表格不出现页面级横向滚动。

### 1280

- 侧栏仍展开或收窄到 `220px`。
- 指标最多四列，长筛选可换行。
- 表格只允许自身容器横向滚动。

### 900

- 侧栏改抽屉，顶栏显示菜单按钮。
- 聊天会话栏可折叠为抽屉。
- 两列详情区改一列；操作按钮不遮挡标题。

### 390

- 页面左右留白 `12-14px`。
- 图标按钮保持至少 `32px` 点击区。
- 表格在局部容器滚动，关键列固定或改为列表摘要。
- 对话框宽度不超过 `calc(100vw - 24px)`。
- 输入器、软键盘、停止按钮和发送按钮不重叠。
- 最长中文/英文文件名截断并可通过 title 或详情查看。

## 10. 实施阶段

### 20.1 设计系统与 AppShell

- 引入 `@lucide/vue`。
- 统一 token、排版、按钮、状态、表格和页面头。
- 重构侧栏、顶栏、面包屑、账号菜单和移动抽屉。
- 保持现有路由与权限判断不变。

### 20.2 用户端页面

- 重做公共入口、认证、工作台、知识库、我的资料和个人中心。
- 把上传、筛选、状态和危险操作改成一致交互。

### 20.3 RAG 与 Agent 工作区

- 提取聊天共享组件。
- 统一会话栏、消息、输入器、引用与 usage。
- Agent 保留公开执行过程、工具、来源、产物、停止和重试。

### 20.4 管理中台

- 统一指标、筛选、数据表、详情抽屉和确认对话框。
- 替换业务 `prompt/confirm`，不增加后端接口。

### 20.5 可访问性与响应式

- 键盘焦点、ARIA、颜色对比、loading/empty/error/permission 状态。
- 验收 1440、1280、900、390。

### 20.6 回归与发布准备

- 运行前端组件测试、SSE、正式构建和必要后端回归。
- 浏览器逐路由检查布局、交互和控制台错误。
- 更新截图、README 和 handoff。
- 本轮先完成本地重设计；部署必须单独确认，不自动改变生产。

## 11. 验收清单

功能：

- 所有原路由可访问，角色导航和后端权限一致。
- RAG/Agent 流式输出、停止、历史、删除、重试、来源和 usage 不回归。
- 知识库上传、审核、任务、角色和额度操作不回归。
- 不新增模型调用、不改变 production shadow/enforce 状态。

视觉：

- 页面不再混用 14px、20px 大圆角和多套卡片阴影。
- 每个页面有明确标题、主操作、状态与数据主体。
- 所有按钮使用一致图标、尺寸和反馈。
- 不出现卡片套卡片、巨型标题、页面级横向滚动或文本遮挡。

验证：

```powershell
D:\Nodejs\npm.cmd --prefix frontend test
D:\Nodejs\npm.cmd --prefix frontend run test:stream
D:\Nodejs\npm.cmd --prefix frontend run build
backend\.venv\Scripts\python.exe -m pytest -q backend/tests
```

浏览器至少覆盖：

- 普通用户：工作台、RAG、Agent、知识库、我的资料、个人中心。
- 管理员：概览、审核、资产、任务、审计、资料、监控、质量、用量。
- 超级管理员：用户、角色与额度。
- 每类代表页面检查 `1440/1280/900/390`，核心聊天页四个宽度全部检查。
