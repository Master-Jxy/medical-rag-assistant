# 当前开发交接

> 最后更新：2026-08-11
> 本文只保留当前事实、工作区边界和一个下一任务。

## 1. 当前真实状态

Stage 25 多模态聊天与输入器升级已完成开发、推送和生产发布。RAG与Agent均支持私有
JPG/PNG/WEBP附件、点击选图、图片粘贴、预览删除、纯图片发送、历史恢复和授权预览。
RAG先形成结构化视觉观察再检索与回答；Agent通过`observe_image`和`inspect_image`
执行每图1次整体观察、最多2次定向补充，并可继续调用公共知识库工具。原图、观察记录、
用量与附件生命周期保持模块化边界，Stage24文档入库视觉Port未被复用。

输入器已改为全宽文本区和底部控制栏；桌面侧栏为220px/收起76px，移动端保持约300px
抽屉。1440、1280、1024和390四视口已完成浏览器验收，收起按钮不再与工作台图标重叠。

Stage 26 已完成本地任务26.0。Agent图片草稿现在复用共享附件状态机并通过
`thread_id + submission_id` registry隔离；提交快照不可变，只有服务端
`message_created`确认后才立即从输入器移除并由历史消息接管，因此同一图片在生成中只
显示一次，A会话结束也不会清空B会话草稿。Composer位于正常三行网格文档流，消息区不再
依赖固定底部留白；历史私有图片预览使用代次令牌丢弃过期异步结果，重复运行提示已合并。
本地Blob URL采用单一所有权：Gallery只释放自己从授权预览响应创建的URL，timeline负责
传入`localUrl`的最终释放。登录切换、登出和401会统一清空模块级草稿、引用、图片与未绑定
已上传asset，上一账号状态不会进入下一账号。
26.0仅使用Fake/静态API浏览器路由，没有真实模型调用、费用、GitHub推送或生产变更。

Stage 26 本地任务26.1也已完成。`/livez`只检查进程，`/readyz`通过应用服务和四个小型
基础设施探针检查MySQL、Redis、Chroma目录及私有媒体目录；失败为503且只返回稳定代码。
基础/ACME/HTTPS Nginx均代理root探针，Compose后端健康检查改用`/readyz`。新增三作业
GitHub CI与统一发布预检；视觉在CI显式Disabled、重试为0，预检不读取`.env`正文且只在
显式传参时访问健康URL。npm审计发现的3个高危传递依赖已固定到修复版本，复查为0。
26.1没有真实模型调用、费用、GitHub推送或生产变更。

Stage 26 本地任务26.2a已完成。迁移`0031_stage26_vision_scope`为历史观察回填非空
`observation_scope_id`和`focus_instruction_hash`，RAG以assistant message、Agent以run作为
观察作用域；新唯一键不再依赖可空外键。视觉repository使用唯一键原子claim，并在MySQL
通过媒体资产行锁串行化每图调用预算；重复并发请求只由一个所有者调用供应商，其余请求
复用终态，失败或停止的相同请求不会自动重试。观察记录增加`route_kind`、
`quality_status`、`quality_codes`和`provider_call_count`，公开`VisionQualitySummary`只包含
确定性质量结论，不保存隐藏推理、用户问题或OCR正文。质量闸门覆盖模糊、裁切、方向、
结构覆盖、报告文字和测量上下文规则。26.2a只运行Fake/本地测试，没有真实模型费用、
GitHub推送或生产变更。

Stage 26 本地任务26.2b已完成开发并通过专项验收。新增聊天专用
`VisionTextExtractionPort`和Disabled/Fake/DashScope OCR-mode适配器，受控提示词不接收
用户问题并把图片内指令视为不可信数据；Stage24知识入库`VisionDocumentPort`及其业务服务
未被复用。`VisionRouterService`先复用整体观察和确定性质量闸门，再选择
`overview_only`、`ocr_mode`或`reupload_required`；OCR提取的可见文字、表格和测量值按
规范化键合并，冲突值保留并公开标记不确定性，空白图不补写内容。RAG、Agent初始整体
观察和`observe_image`均进入Router，`inspect_image`继续使用原服务，所以overview、OCR和
定向观察共同占用每图最多3次供应商调用。

OCR以`report_extract`记录进入既有原子claim、媒体资产行锁、额度预留/结算和脱敏usage
账本；终态重放及并发请求不重复调用或计费，供应商已经返回usage而后续持久化失败时仍按
实际usage结算，供应商未消费才释放。OCR默认Disabled，自动重试保持0。固定评估集包含8张
程序生成的无隐私PNG、SHA-256 manifest、可重建脚本和无费用Fake评估，覆盖普通图片、中文
界面、中英混排、表格、明确标注的虚构报告、模糊、裁切和空白。未读取真实资料、`.env`或
密钥，未调用真实模型，未产生费用，也未开始26.3。按当前检查点要求，完整后端回归未在
提交前执行，需作为26.2b唯一剩余收口项。

26.2b总控审查的4个P1已修复：`0031`恢复原已发布route constraint，新增
`0032_stage26_vision_ocr_routes`扩展OCR路由并在降级时把`ocr_mode`映射为`report`、另外
两个新值映射为`general`；因此26.3任务租约迁移顺延为`0033_stage26_job_leases`。DashScope
在HTTP 200后若JSON或schema解析失败，会通过受控异常把usage、model和供应商request ID
交给应用服务，写failed `ModelUsageRecord`并按实际或unknown usage结算，观察记录终态失败且
同请求不再调用。RAG/Agent历史查询过滤内部`report_extract`，只公开最终merged overview并
保留focused。固定资产评估明确为Fake契约评估，在读取PNG前验证schema、零重试、synthetic
隐私、case/file/hash唯一、PNG basename、目录包含关系及symlink/穿越拒绝。CI也显式关闭
OCR。以上只使用Fake和本地合成资产，没有真实模型调用。

生产当前状态：

- GitHub `main`：`b8e1719fa3be90b53822e58f07d2179737ae46b6`。
- 服务器工作区：同一提交，工作区干净。
- 备份：`/home/deploy/medical-rag-backups/backup-20260810T003429Z`，7项SHA-256通过。
- 数据库迁移：`0030_multimodal_chat_assets (head)`。
- 容器：backend、web、mysql、redis均为healthy。
- 网络：HTTP 80返回308；HTTPS首页和`/api/v1/health`返回200。
- 静态资产：`index-CPEwi2bu.js`、`index-Xv-mGLQX.css`。
- 视觉配置：enabled / DashScope / `qwen3-vl-plus` / automatic retries 0。

生产容器内使用内存生成的非医疗测试图完成一次无持久化真实视觉烟测：
`production_vision=PASS`，输入311 Token、输出155 Token、总计466 Token，measurement为
actual，请求ID存在。DashScope偶发把`objects`等字段返回为对象而非字符串，提交
`95f856d`已在基础设施适配器归一化该格式，并增加回归测试；发布后近15分钟后端错误
标记为0。

完整设计与证据见：

- `docs/stage25-multimodal-chat-design.md`
- `docs/technical-design.md`的Stage25章节
- `docs/release-audit-stage25-multimodal-chat.md`
- `docs/development-roadmap.md`的Stage25章节

## 2. 验证结果

```text
Stage25 vision focused
7 passed

backend full suite（从仓库根目录执行）
637 passed, 1 skipped

frontend full suite
22 files / 90 tests passed

SSE parser
PASS

Vite production build
PASS: index-Xv-mGLQX.css / index-CPEwi2bu.js

Alembic temporary roundtrip
0029 -> 0030 -> 0029 -> 0030 PASS

Playwright no-cost browser acceptance
1440x900 / 1280x800 / 1024x768 / 390x844 PASS

Stage26.0 focused
Agent draft/timeline/gallery/auth lifecycle: 30 passed
impeccable detector: []
browser: 3 images + 4 lines, A/B draft isolation, no overlap/overflow,
console 0 error / 0 warning

Stage26.1 focused
readiness / preflight / deployment: 18 passed
Alembic temporary roundtrip: 0029 -> 0030 -> 0029 -> 0030 PASS
Python compile/import: PASS
Compose base + HTTPS config: PASS
pip check: PASS
npm audit: 0 vulnerabilities
release preflight: PASS 2 / SKIP 5（本地受保护dirty文件边界）

Stage26.2a focused
vision scope / quality / concurrency: 9 passed
Stage25 multimodal + migration regression: 34 passed
Alembic temporary roundtrip: 0030 -> 0031 -> 0030 -> 0031 PASS
backend full suite: 637 passed, 1 skipped
Python compile/import: PASS

Stage26.2b focused
chat OCR adapters / controlled prompt / merge / persisted replay /
concurrent quota / shared three-call budget / failure settlement / fixed assets: 9 passed
Stage25 vision regression: 9 passed
combined focused: 18 passed
no-cost fixed asset evaluation: 8 assets, hash/schema/route/text/measurement/table = 1.0,
blank hallucinations = 0, duplicate provider calls/usage charges = 0,
real model calls = 0
Alembic temporary roundtrip: 0030 -> 0031 -> 0030 -> 0031 PASS
Focused Python compile: PASS
backend full suite: NOT RUN（按检查点要求先提交可审查commit）

Stage26.2b P1 review fixes focused
DashScope consumed-invalid-response accounting / single SDK call failures /
history filtering after SSE / Fake contract manifest rejection /
overview+OCR+focused final-budget race / Stage25 image regressions: PASS
combined focused and migration matrix: 37 passed
Alembic: 0031 original constraint PASS
Alembic: 0031 -> 0032 -> 0031 -> 0032 with downgrade mapping PASS
backend full suite from repo root: 660 passed, 1 skipped

Protected auth SHA-256
9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0
```

## 3. 工作区与安全边界

- 当前分支：`main`。
- `backend/app/modules/auth/service.py`仍是用户受保护的未提交改动。禁止读取正文、修改、
  格式化、暂存、提交、回退或覆盖；只允许核对上面的SHA-256。
- 不读取或提交`.env`、真实上传资料、Chroma数据、数据库备份或正文日志。
- 真实模型测试必须使用非医疗测试资产，只输出脱敏计量与结果状态；禁止无限重试。
- 生产继续使用`compose.yaml`和`deploy/compose.https.yaml`，禁止`docker compose down -v`，
  禁止修改MySQL、Redis、Chroma和app_data数据卷。

## 4. 新任务阅读范围

新窗口先完整阅读`AGENTS.md`、本文和`docs/stage26-enterprise-hardening-design.md`。
26.3开发只定向读取：

- `processing_jobs`模型、repository、service、API和既有资料发布补偿服务
- Compose服务、迁移链和后台任务页面的直接依赖
- `auth/service.py`继续只核对SHA-256，不读取正文

普通观察期不要全文读取历史技术设计、旧发布审计或大型评估JSON。

## 5. Stage 26授权范围

用户已授权按照`docs/stage26-enterprise-hardening-design.md`依次完成六类企业强化、完整
测试、GitHub推送和生产部署。真实模型只允许使用无隐私固定资产和受控调用上限；禁止
读取密钥正文或把密钥写入Git、日志和文档。

## 6. Stage26.3 收口证据

- `0032 -> 0033 -> 0032 -> 0033`迁移矩阵通过。
- 队列、租约、独占领取、过期回收、有限重试、取消和Worker执行专项：`37 passed`。
- 管理员批准发布返回`202 + job_id`；Worker复用共享资料生命周期并完成成功/失败补偿。
- Compose新增独立`worker`服务；Worker不参与人工`knowledge_review`任务，也不阻断API/Web健康链路。

## 7. 唯一下一任务

**开始26.4：建立可执行`corpus_v2/eval_v2`质量闭环；不得伪造医学语料，缺少人工合法资料时输出
`not_eligible`，并把候选池16、同文档最多2片段、最终4片段及排序晋级门槛做成可运行配置。**
