# 当前开发交接

> 最后更新：2026-08-03
> 本文件只保留当前事实、工作区边界和一个下一任务。

## 1. 当前真实状态

Stage 22 的 22.1～22.8 已完成并发布。GitHub 和生产提交均为 `5c02056`，生产 Alembic
head 为 `0026_stage22_runtime_contract`。生产使用 HTTPS 入口，MySQL、Redis、应用数据和
Chroma 数据卷均保留，Stage 22 没有启用新的真实模型调用。

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

## 2. 本地验证结果

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
```

浏览器无模型/无持久化 stub 验收通过：桌面和 390px 移动端均完成 RAG/Agent 并发、独立
停止、后台未读、重新打开清除未读、运行中删除禁用、四种 Agent 模式、固定输入器和溢出
检查，控制台无错误。真实本地 MySQL 连接拒绝，因此没有把本地结果写成真实 MySQL 验收。

## 3. 生产发布证据

- 生产备份目录：`/home/deploy/medical-rag-backups/backup-20260803T012857Z`。
- 备份中的 MySQL、app_data、chroma_data、redis_data、deploy.env、compose.yaml 和 manifest 均通过 `SHA256SUMS` 校验。
- 服务器从 `8d529298` 快进到 `5c020561`，随后只重建 backend 和 web；MySQL/Redis 容器和四类数据卷没有重建。
- backend 启动日志确认执行 `0025_quota_policy_v2 -> 0026_stage22_runtime_contract`，四容器最终均为 healthy。
- 公网 HTTP 返回 308 到 HTTPS；HTTPS `/api/v1/health` 返回200；未登录 `/api/v1/conversations` 返回401。
- 线上服务的 JS/CSS SHA-256 与本地 `frontend/dist` 匹配：`index-DjpPtGBX.js`、`index-LYaCnDip.css`。
- 发布前后核心数量不变：users 14、conversations 9、messages 150、documents 27、agent_threads 6、agent_messages 58。
- 发布后的 backend/web 日志没有 traceback、exception、critical 或 error。
- 本次没有调用真实 Qwen、Embedding、Reranker 或 SMTP；额度策略保持 shadow，自动记忆提取保持关闭。

## 4. 工作区与安全边界

- 当前分支 `main` 已推送 `5c02056`；工作区只剩 `backend/app/modules/auth/service.py` 的既有用户修改，禁止修改、格式化、暂存、提交或回退。
- 受保护文件当前 SHA-256 为 `9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0`。
- 不读取或提交 `.env`、SMTP 授权码、API Key、上传文件、Chroma 数据、日志或数据库备份。
- 生产服务器工作区已同步指定提交；`frontend/dist` 是构建输入，不作为源代码提交。

## 5. 已知后续风险

- 后端进程崩溃后，遗留的 RAG `pending` 记录仍需要独立的恢复策略；本阶段通过状态展示和删除保护避免误操作，但没有擅自引入超时清理。
- Agent 的 `stopping` 主要由当前运行态和前端状态承载；刷新期间的持久化停止提示可作为后续 UX 小任务。
- 无工具的短 Agent 回复可以由规划调用一次性生成一个 token 事件；它仍符合 SSE 契约，工具型回答保持逐块输出，未为此改变公开事件或隐藏推理边界。

## 6. 新任务阅读范围

新开发窗口先完整阅读 `AGENTS.md` 和本文件，再按任务定向读取对应源码、测试和设计文档。
不要读取历史 RAG 评估 JSON，不调用真实模型，不读取真实密钥，不修改受保护 auth Service。

## 7. 唯一下一任务

**评估并单独设计 Stage 23：运行中断恢复策略。**

只做方案和影响评估，重点比较 RAG stale `pending` 的超时收敛、Agent `stopping` 刷新恢复、
数据库状态与前端 stream registry 的一致性；先不启用自动清理、不改变生产开关、不调用真实
模型，确认回滚和数据保护边界后再拆成实现任务。
