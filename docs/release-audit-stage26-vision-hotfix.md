# Stage 26 多模态聊天持久化热修复发布审计

> 发布日期：2026-08-11
> 应用提交：`3441ccd5d402f2dc0a25323f29d4797da9e0d1f3`
> 发布目标：修复生产 RAG/Agent 带图请求失败、历史附件丢失及失败草稿重复问题。

## 1. 故障与根因

生产日志中的直接故障为 MySQL 拒绝写入超长 `idempotency_key`：视觉额度幂等键拼接了
surface、用户、资产、作用域、操作等多个原始字段，最终超过数据库 `VARCHAR(128)`，触发
`Data too long for column 'idempotency_key'`。视觉调用因额度记录无法持久化而中断，表现为：

- RAG 带图请求返回 HTTP 500；
- Agent 带图任务在形成有效工具链前失败；
- 前端未收到完整持久化事件时，乐观附件与历史附件的所有权判断错误；
- 失败后草稿图片可能继续留在输入器，与已经落库的历史消息重复。

## 2. 修复内容

### 后端

- `vision/service.py` 使用 `vision:<operation>:<sha256>` 构造稳定、定长的视觉额度幂等键，
  覆盖 `overview`、`focused` 和 `report_extract`。
- `usage/quota_service.py` 在统一额度入口增加长度防御：超过 128 字符时保留短前缀并追加
  SHA-256，不使用可能发生碰撞的简单截断。
- 新增回归测试，覆盖键长度、稳定性、scope/focus 区分和额度持久化。

### 前端

- RAG 历史消息完整保留 `attachments` 与 `vision_observations`。
- 当 SSE 关键事件缺失但服务端已经落库时，历史消息接管附件并删除重复乐观消息。
- 页面离开和失败恢复不再误删已绑定图片；非运行状态使用服务端消息刷新流缓存。
- Agent 草稿注册表支持在服务端确认前保留本地预览 URL，并在确认落库后正确交接所有权。
- 新增 RAG、Agent 对应的失败、恢复和附件交接回归测试。

## 3. 本地验证

| 验证项 | 结果 |
|---|---|
| 后端完整测试 | `692 passed, 1 skipped` |
| 前端完整测试 | `22 files / 92 tests passed` |
| 视觉定向回归 | `34 passed` |
| SSE 回归 | PASS |
| Vite build | PASS |
| `git diff --check` | PASS |
| 认证保护文件 SHA-256 | `9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0` |

构建产物：

- `frontend/dist/assets/index-C46rS-BD.css`
- `frontend/dist/assets/index-td6eTMCU.js`

完整测试前将 Windows `TEMP`、`TMP` 和 pytest `basetemp` 固定到 D 盘；清理本次 pytest
临时目录后，C 盘从 0 KB 恢复到约 12 GB 可用。该约束已写入 `AGENTS.md`，后续测试、
构建缓存、浏览器验收资产和日志优先使用
`D:\软件大合集\软件缓存\codex-test-temp\medical-rag-assistant`。

## 4. 生产发布

- 发布前备份：`/home/deploy/medical-rag-backups/backup-20260811T033701Z`。
- 前端上传产物逐项通过 SHA-256 校验，旧 `frontend/dist` 已保存在上述备份目录。
- 服务器访问 GitHub 时发生一次 TLS 中断；改用本地验证过的 Git bundle，由 Git 执行
  `41960066 -> 3441ccd5` 快进，未直接复制或修改服务器业务源码。
- 数据库迁移：`0033_stage26_job_leases (head)`，没有重建或删除数据卷。
- backend、worker、web 均重新构建；MySQL、Redis 数据容器保持原位。
- HTTP 首页返回 308，HTTPS 首页返回 200；`/livez` 和 `/readyz` 均通过。
- 五个容器重启计数均为 0；根盘使用率 33%，可用约 26 GB。
- `deploy/post_release_check.sh` 全部适用项目通过；证书域名参数未传入的两项按脚本设计跳过。

## 5. 真实带图验收

验收使用内存生成的无隐私、非医疗 PNG，视觉模型为 DashScope，自动重试固定为 0。
测试通过短期内部令牌使用现有活跃账号，不读取邮箱、密码、API Key 或用户资料正文。

| 场景 | 结果 | 关键证据 |
|---|---|---|
| RAG 带图流式问答 | PASS | HTTP 200；包含 `vision_observations`、`token`、`sources`、`done` |
| RAG 历史恢复 | PASS | 1 个附件、1 份视觉观察，授权预览返回图片 |
| Agent 带图任务 | PASS | 包含 `tool_started`、`tool_completed`、`vision_observations`、`message_completed` |
| Agent 历史恢复 | PASS | 1 个附件、1 份视觉观察、1 条 completed assistant 消息 |
| 临时数据清理 | PASS | 会话 0、Agent 线程 0、附件绑定 0、媒体文件 0 |
| 发布后错误检查 | PASS | 最近错误标记 0 |

数据库保留 2 条状态为 `deleted` 的合成图片元数据，作为正常生命周期审计；原始文件、消息、
附件绑定、会话和线程均已删除。

## 6. 回滚边界

- 应用回滚点：`419600666898cc8c35ee9edb9f1ac837587fc096`。
- 数据与前端备份：`/home/deploy/medical-rag-backups/backup-20260811T033701Z`。
- 本次迁移没有新增 schema，回滚应用代码不需要执行数据库降级。
- 禁止使用 `docker compose down -v`；回滚不得删除 MySQL、Redis、Chroma、app_data 或
  私有媒体数据卷。

## 7. 发布结论

本次热修复已完成开发、完整回归、GitHub 推送、生产部署和真实 RAG/Agent 带图验收。
原故障路径不再出现 HTTP 500 或 0 工具失败，附件持久化、历史预览和前端所有权交接均有
自动化回归覆盖。后续进入观察期，不因本次故障继续扩大改动范围。
