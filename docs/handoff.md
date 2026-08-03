# 当前开发交接

> 最后更新：2026-08-03
> 本文件只保留当前事实、工作区边界和一个下一任务。

## 1. 当前真实状态

Stage 22 的 22.1～22.7 已在本地完成，代码尚未提交、推送或发布。生产仍停留在
Stage 21.2 提交 `8d52929`、数据库 `0025_quota_policy_v2`；Stage 22 尚未执行生产迁移。

本阶段已实现：

- 管理员统一替换和永久删除系统资料、用户审核后发布的资料；普通用户不能永久删除已发布公共资料。替换保留上传者、标签、分类、科室和治理元数据，并同步关联 submission。
- 跨 MySQL、文件和 Chroma 的删除/替换继续使用行锁、审计和可补偿流程。
- 新增迁移 `0026_stage22_runtime_contract`：RAG 会话和 Agent thread 增加 `last_read_sequence`，Agent thread 增加 `assistant_mode`。
- 会话列表返回运行状态、active run、未读状态和最后消息状态；read marker 只能前移。
- RAG 与 Agent 共用每用户并发槽位，默认最多同时运行 2 个不同会话；同一会话仍保持单生成锁。
- RAG 与 Agent 前端均使用按会话 stream registry。会话 A 生成时可切换或新建会话 B，并在 B 继续提问；A 后台完成后显示未读点，重新打开后清除。
- 停止只影响当前选中会话；运行中的会话不能删除或归档。
- Agent 增加 `general/patient/clinician/knowledge` 四种后端强制模式。
- Agent 增加受控 supervisor/specialist 路由：最多 2 个 specialist、1 次 handoff、3 次工具调用、4 次模型调用。它不是自由群聊式或并行多 Agent。
- 显式引用可解析已有来源；工具结果摘要限制为 1200 字符；确定性工具结果跳过不必要的 inspection 模型调用；重复澄清键阻止相同循环。
- 公开计划和事件只来自后端白名单模板，不展示或持久化模型隐藏推理。

完整设计和对标证据：

- `docs/stage22-concurrent-agent-and-governance-design.md`
- `docs/stage22-benchmark-and-design-research.md`

## 2. 当前验证结果

```text
backend\.venv\Scripts\python.exe -m pytest -q backend/tests
469 passed, 113 warnings

D:\Nodejs\npm.cmd --prefix frontend test
18 files / 70 tests passed

D:\Nodejs\npm.cmd --prefix frontend run test:stream
SSE parser test passed

D:\Nodejs\npm.cmd --prefix frontend run build
Vite production build passed
assets: index-LYaCnDip.css / index-DjpPtGBX.js

backend\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini heads
0026_stage22_runtime_contract (head)

git diff --check
passed; only expected Windows line-ending notices

Protected auth hash
9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0

Browser acceptance with no-model/no-persistence stub
Desktop and 390px mobile passed: RAG A/B concurrent generation, independent stop,
background unread marker, reopen clears unread, running delete disabled, overflow 0,
and no console errors. Agent equivalents and four mode selection also passed earlier.
```

本轮没有调用真实 Qwen、Embedding、Reranker 或 SMTP。真实 MySQL 迁移将在生产备份后执行；
本机 MySQL 连接拒绝，因此不能把本地结果写成真实 MySQL 验收。

## 3. 工作区与安全边界

- 当前分支 `main`，任务开始基线 `5d84f59`；Stage 22 修改尚未提交。
- `backend/app/modules/auth/service.py` 是任务开始前已有的用户修改，禁止修改、格式化、暂存、提交或回退；当前 SHA-256 为 `9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0`。
- 不读取或提交 `.env`、SMTP 授权码、API Key、上传文件、Chroma 数据、日志或数据库备份。
- 提交时必须显式排除上述 auth Service；推送、SSH、生产备份、迁移和部署已由用户在本次对话明确授权。
- 额度策略继续保持 shadow，自动记忆提取继续关闭；本阶段不改变真实模型调用开关。

## 4. 已知后续风险

- 后端进程崩溃后，遗留的 RAG `pending` 记录仍需要独立的恢复策略；本阶段通过状态展示和删除保护避免误操作，但没有擅自引入超时清理。
- Agent 的 `stopping` 主要由当前运行态和前端状态承载；刷新期间的持久化停止提示可作为后续 UX 小任务。
- 无工具的短 Agent 回复可以由规划调用一次性生成一个 token 事件；它仍符合 SSE 契约，工具型回答保持逐块输出，未为此改变公开事件或隐藏推理边界。

## 5. 本任务阅读范围

新开发窗口先完整阅读 `AGENTS.md` 和本文件，再按任务定向读取：

- `docs/stage22-concurrent-agent-and-governance-design.md`
- `backend/alembic/versions/0026_stage22_runtime_contract.py`
- `frontend/src/features/agent-chat/useConversationStreamRegistry.js`
- `frontend/src/views/ChatView.vue`
- `frontend/src/views/AgentView.vue`
- `frontend/src/views/AdminAssetsView.vue`
- Stage 22 对应迁移、并发、Agent 和前端测试

不要读取历史 RAG 评估 JSON，不调用真实模型，不读取真实密钥，不修改受保护 auth Service。

## 6. 唯一下一任务

**Stage 22.8 提交、推送与生产发布。**

先检查完整差异并确认 `auth/service.py` 不在提交范围；提交并推送指定 SHA，上传同一次本地
Vite 构建的 `frontend/dist`，在服务器执行受控备份，拉取指定提交，执行 `0025 -> 0026`
迁移，仅重建 `backend` 和 `web`，不重建 MySQL/Redis 数据卷。完成四容器健康、迁移 head、
HTTPS/HTTP 路由、未授权 401、静态资源哈希和数据数量不变的线上无费用验收后，把本文件更新
为发布事实，并留下一个后续任务。
