# Stage 26 企业交付强化设计

> 日期：2026-08-11
> 状态：设计冻结，待按26.0至26.8顺序开发
> 目标：在现有模块化单体、Stage25多模态链路和2核2G单机部署边界内，补齐视觉质量、RAG质量、Agent工具、后台任务、模型与额度、可观测性六个企业闭环，并修复Agent图片输入器状态混乱。

## 1. 交付范围

Stage26不是重写项目。以下稳定能力继续复用：

- 私有图片资产、图片所有权、预览、删除和会话级清理；
- `VisionObservation`、每图1次整体加最多2次定向观察、视觉usage与额度结算；
- RAG Port、检索资格、混合检索/Reranker候选、评估资产和人工反馈；
- Agent工具白名单、LangGraph有界循环、摘要、资料对比、学习报告和来源；
- `processing_jobs`状态表、文档发布补偿、资料审核与治理；
- MySQL额度真相源、`off/shadow/enforce`、预留/结算/释放和用量中心；
- request ID、脱敏JSON日志、阶段耗时、Docker健康、HTTPS、备份与恢复。

本阶段明确不做：

- 多Agent、自由网页浏览、代码执行、插件市场；
- Kubernetes、微服务拆分、分布式消息中间件；
- 未经审核的互联网医学资料自动入库；
- 自动诊断、处方或治疗决策；
- 为展示技术栈而同时接入多个未验证供应商。

## 2. 目标架构

```text
Vue工作台
  -> FastAPI API / SSE
       -> 应用服务
          -> VisionRouter -> VL / OCR-mode adapter -> VisionQualityGate
          -> RAG Search -> candidate policy -> optional rerank -> answer
          -> Bounded Agent -> versioned read-only tools
          -> JobDispatcher -> MySQL queue
       -> MySQL / Chroma / Redis / private media

独立Worker容器
  -> MySQL lease claim
  -> 复用公开应用服务
  -> heartbeat / progress / retry / cancel / dead-letter

运维旁路
  -> livez / readyz / metrics
  -> JSON logs / SLO snapshot / GitHub Actions
```

API、Worker和Agent工具都只能调用公开应用服务。禁止在Worker中复制文档发布逻辑，禁止Agent工具直接访问SQLAlchemy、Chroma、文件路径或供应商SDK。

## 3. 26.0 Agent图片输入器修复

### 3.1 已确认根因

1. 图片草稿直到整条SSE结束才清理，同一图片在生成期间同时显示为“待发送”和历史消息。
2. 草稿没有按`thread_id`隔离，A会话完成可能清空B会话正在编辑的内容。
3. Composer绝对定位且消息区只写死108px底部留白，附件、引用、错误或四行输入会遮挡消息。
4. 顶部运行状态、执行过程、thinking气泡和停止按钮重复表达同一状态。
5. 历史图片异步预览没有代次保护，旧请求可能覆盖新消息并导致布局跳动。

### 3.2 状态机

```text
editing
  -> uploading
  -> awaiting_acceptance
  -> accepted_running      message_created后草稿立即移除
  -> completed/stopped/failed_after_accept

upload_failed/failed_before_accept
  -> editing               原文字、引用和附件可重试恢复
```

草稿真相键为`thread_id + submission_id`。流完成只能结算所属submission，禁止无条件清空当前Composer。

### 3.3 前端实现

- 新增轻量`agentDraftRegistry`，按线程保存文字、引用、附件和submission状态，不引入Pinia。
- `AgentComposer`提交不可变submission；`message_created`事件触发`acceptDraft`。
- `AgentView`删除SSE结束后的无条件`completeSend()`。
- `conversation-shell`改为`42px minmax(0,1fr) auto`三行网格，Composer回到正常文档流。
- 草稿图固定约72x54，历史图固定约112x84，圆角不超过8px；图片、文件名和文字属于同一用户消息表面。
- 活跃助手消息没有正文时只显示一处展开进度；首个Token后再显示回答正文。
- 历史预览预留尺寸并使用generation token丢弃过期异步结果。

### 3.4 验收

- 发送后图片只出现一次，`message_created`后输入器立即恢复可编辑。
- A带图生成时切换B，B不出现A草稿；A结束不清空B草稿。
- 1至3图、1至4行文字、引用和错误提示不遮挡最后一条消息。
- 图片only、图片加文字、停止、失败、刷新恢复和多会话并发均通过。
- 1440x900、1280x800、1024x768、390x844浏览器验收，控制台0错误。

## 4. 26.1 CI、健康检查与发布基线

先建立后续改动的自动防线：

- 保持`/api/v1/health`兼容；新增`/livez`只检查进程存活。
- 新增`/readyz`，以短超时检查MySQL、Redis、Chroma目录和私有媒体目录；不初始化模型、不调用外部服务。
- 增加`.github/workflows/ci.yml`：后端完整测试、前端测试、SSE测试、Vite build、Alembic往返、`git diff --check`、敏感文件扫描和依赖基础审计。
- 增加统一发布预检脚本，输出PASS/FAIL/SKIP，不读取`.env`正文。
- readiness失败返回503和稳定依赖代码，不回传地址、账号、路径或异常正文。

## 5. 26.2 视觉质量与OCR路由

### 5.1 调用流程

```text
图片解码与轻量探测
-> overview VL观察
-> VisionQualityGate
   -> 普通照片且信息完整：交给RAG/Agent
   -> 文字密集/表格/报告且文字不足：OCR-mode定向提取
   -> 模糊、截断、方向异常：提示重新上传
   -> 医学影像诊断请求：只描述可见事实并保留安全边界
-> 合并派生观察
-> 主模型决定检索、工具或回答
```

### 5.2 模块边界

- `vision/router_service.py`：只做路由和调用编排。
- `vision/quality.py`：确定性完整度、字段覆盖和不确定性规则，不调用模型。
- `VisionTextExtractionPort`：聊天图片文字提取的小型Port。
- `infrastructure/dashscope_chat_ocr.py`：使用受控OCR提示词调用现有多模态供应商；不得复用文档入库审批Port。
- `VisionObservation`增加公开质量摘要，但不保存隐藏推理。

### 5.3 幂等与数据

迁移`0031_stage26_vision_scope`：

- 为观察增加非空`observation_scope_id`；RAG使用assistant message，Agent使用run。
- 唯一键改为`media_asset_id + observation_scope_id + kind + focus_hash`，避免MySQL NULL唯一键绕过。
- 增加`route_kind`、`quality_status`、`quality_codes`和`provider_call_count`等脱敏字段。

每图仍最多3次视觉类调用；OCR-mode占用调用预算，自动重试仍为0。重复请求不得重复调用或重复计费。

### 5.4 测试集

固定无隐私图片覆盖普通图片、中文截图、中英混排、表格、检查报告、模糊图、裁切图和空白图。指标至少包括：结构校验成功率、可见文字覆盖、测量字段完整率、质量路由准确率、重复计费次数和平均Token。

## 6. 26.3 MySQL后台任务与Worker

当前`processing_jobs`只是状态记录，本阶段升级为单机可靠队列。

迁移`0032_job_leases`增加：

- `dispatch_key`唯一调度键；
- `available_at`、`max_attempts`；
- `lease_owner`、`lease_expires_at`、`heartbeat_at`；
- `cancel_requested_at`和`last_error_code`；
- queued/lease索引。

状态流转：

```text
queued -> running -> completed
                -> retry_wait -> queued
                -> failed
                -> cancelled
```

- API事务内创建queued job并返回`202 + job_id`。
- 独立`worker`容器使用`FOR UPDATE SKIP LOCKED`领取任务，定期心跳。
- 崩溃租约到期后可重新领取；指数退避有上限，禁止无限重试。
- 发布、解析、Embedding和Chroma写入继续复用现有文档生命周期与补偿服务。
- 管理员任务页增加详情、取消、重试、租约/尝试状态；不显示正文和堆栈。
- 第一批迁移资料发布与文档增强任务；定时清理只作为独立低优先级job。

## 7. 26.4 知识库与RAG质量闭环

不直接把互联网资料塞进生产。交付内容是可持续质量体系：

- 将`corpus_v2`从placeholder改为可执行manifest：来源、许可、科室、疾病、文档类型、年份、版本和ready状态齐全才可进入评估。
- 增加批量资料预检、重复/版本/覆盖缺口报告；管理员确认后才进入现有审核链路。
- 新增`run_eval_v2`无费用模式和差异报告，覆盖检索、排序、引用、拒答、OCR、表格和版本失效。
- 评分器支持同义表达与结构化事实，禁止只用固定短语或精确子串代表医学正确。
- CI只运行Fake/fixture门禁；真实Embedding、Reranker和Qwen评估必须有调用上限和独立审计。
- 候选池默认16，同一文档默认最多2片段，最终返回4片段；混合检索和Reranker只有超过冻结门槛才晋级，未晋级继续关闭。
- 管理后台展示语料ready数、覆盖缺口、最近评估版本和候选晋级结论。

资料数量本身不是代码验收项；合法来源、内容审核和真实黄金答案必须由人工确认。系统不得生成伪造医学资料冒充高质量语料。

## 8. 26.5 Agent确定性工具与评估

已有摘要、对比和学习报告不重做。新增第一批只读确定性工具：

- `calculator`：仅允许白名单算术表达式，不使用`eval`；
- `get_document_section`：按已发布资料的结构化章节读取；
- `extract_table`：返回已解析表格，不从任意正文猜表格；
- `verify_citations`：核对最终引用是否来自本次工具结果和已发布资料；
- `extract_measurements`：从结构化视觉观察提取指标，不作诊断；
- `draft_follow_up_plan`：基于用户目标和已发布资料生成随访问题清单草稿，明确非诊疗建议。

工具元数据包括版本、风险级别、权限、超时、调用预算和是否产生模型费用。新增只读`GET /api/v1/agent/tools`。评估集覆盖工具选择、错误参数、超时、预算、视觉、停止恢复、来源真实性和拒答；不增加多Agent。

## 9. 26.6 模型网关与真实额度限制

### 9.1 模型网关

- 新增`ModelGatewayPort`与静态`ModelRoutePolicy`，替代业务代码直接创建供应商模型。
- 路由维度：surface、task_kind、是否有图片、复杂度上限、用户允许模型。
- 首版只开放已验证的DashScope模型：通用/高质量文本与视觉路由；目录占位模型不得显示为可用。
- 用户显式选择必须经过能力、权限和额度校验；服务端仍是最终真相。
- 仅连接超时、限流和明确临时错误允许一次受控fallback；安全拒答、参数错误和额度不足禁止fallback。
- 主调用和fallback统一写入同一usage group并分别计费，避免隐藏双倍成本。
- 管理员只读查看路由健康、失败分类和最近fallback，不在页面编辑密钥。

### 9.2 额度

- 默认月额度保持100万Token，角色仍只有user/admin/super_admin。
- 完整覆盖RAG、Agent、视觉、OCR-mode、Rerank和后台模型任务。
- 生产先做shadow对账；确认预留、结算、释放、未知计量和现有用户余量后切换`enforce`。
- 超额返回稳定错误和剩余额度；前端显示预警、预计恢复时间和本轮实际消耗。
- 管理员只读全站用量，只有super_admin可以审计地调整额度。

## 10. 26.7 可观测性与生产稳定

- 统一HTTP、RAG、Agent、Vision/OCR、Job、Quota和ModelGateway事件字段。
- 增加请求错误率、P50/P95、各阶段耗时、视觉质量失败、工具成功率、队列等待/运行时长、租约回收、fallback、未知计量和额度拒绝指标。
- `/metrics`默认关闭；启用时必须使用独立Bearer token或仅绑定内网，不带用户ID、问题、OCR正文、request ID等高基数标签。
- 管理后台SLO页展示滚动窗口摘要和稳定错误码；重启归零的进程指标必须明确标识，不能冒充历史趋势。
- 增加陈旧job、孤儿媒体、过期额度预留和备份新鲜度检查。
- 发布后检查日志错误标记、磁盘、内存、容器重启次数和证书余量。
- 保留单机部署，不增加Prometheus/Grafana常驻容器；先提供可抓取接口和外部接入点。

## 11. 开发顺序

1. **26.0** Agent图片输入器状态机和布局修复。
2. **26.1** CI、livez/readyz和发布预检。
3. **26.2a** 视觉幂等作用域与质量规则。
4. **26.2b** OCR-mode适配器、路由与固定图片评估。
5. **26.3** MySQL租约队列、Worker和任务中心。
6. **26.4** corpus_v2/eval_v2质量闭环与管理摘要。
7. **26.5** Agent确定性工具和完整回归集。
8. **26.6a** 模型网关与真实目录。
9. **26.6b** 全surface额度对账并受控切换enforce。
10. **26.7** 指标、SLO和生产稳定检查。
11. **26.8** 完整测试、迁移往返、浏览器验收、备份、部署和真实黑盒验收。

禁止跳过26.0/26.1直接改Worker或模型路由。每个任务完成后更新handoff，只保留一个下一任务；失败时停在当前任务，不把后续任务标记完成。

## 12. 分级验证与费用闸门

每一步先Fake/无费用验证。共享Port、迁移、会话、额度和任务队列改动必须运行完整后端；前端改动运行完整前端、SSE、build和四视口浏览器验收。

真实供应商验收必须满足：

- 使用非医疗、无隐私固定资产；
- 调用前打印模型、调用次数上限、最大Token和预计费用；
- 自动重试为0；fallback默认关闭；
- 只输出PASS/FAIL、Token、请求ID是否存在和稳定错误码；
- 失败达到停止条件立即结束，不为了过测试循环付费调用。

## 13. 发布与回滚

- 保护`backend/app/modules/auth/service.py`既有用户改动及其SHA-256。
- 发布前先推送GitHub、创建外置完整备份并校验SHA-256。
- 继续使用`compose.yaml + deploy/compose.https.yaml`，禁止`down -v`。
- 新增Worker时先迁移数据库，再启动Worker；Worker失败不得阻断RAG/Agent读取服务。
- 模型网关、OCR路由、Worker和额度enforce使用独立开关，可分别回退。
- 回滚只快进/回退应用提交和对应迁移；涉及已产生新业务数据时优先整体备份恢复，不盲目降级删表。

## 14. 完成定义

Stage26只有在以下证据全部存在时完成：

1. 六个优先级均有真实代码/API或明确可运行运维入口，不以文档占位代替实现。
2. Agent带图发送在生成中只显示一次，跨会话草稿隔离通过。
3. 视觉质量/OCR路由有固定图片集、幂等和计费测试。
4. Worker真实独立进程完成至少一种长任务，并通过崩溃租约回收测试。
5. eval_v2可执行且能输出晋级/不晋级结论，不伪造语料质量。
6. 新Agent工具均有权限、参数、来源和预算测试。
7. 模型目录只暴露真实可用模型，额度覆盖所有模型surface并完成enforce前对账。
8. livez、readyz、CI和SLO检查通过。
9. 完整后端、前端、SSE、build、迁移往返和四视口浏览器验收通过。
10. GitHub、生产提交、迁移、容器、HTTP/HTTPS、日志和回滚证据记录在发布审计中。
