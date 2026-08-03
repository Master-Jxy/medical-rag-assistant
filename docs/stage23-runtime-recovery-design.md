# Stage 23：运行中断恢复

## 1. 目标

Stage 22 已经让 RAG 和 Agent 支持多会话运行、停止、刷新恢复和未读状态，但两类
运行记录的持久化边界不同：

- RAG 的助手消息在开始生成时写成 pending。如果后端进程在模型返回前退出，
  这条消息可能永久显示为“生成中”。
- Agent 的 AgentRun、AgentStep 和 AgentMessage 已有进程重启收敛逻辑。
  Agent 的 stopping 主要是当前进程中的取消信号，不应为了刷新提示再增加一套
  数据库状态。
- 前端 stream registry 只代表当前浏览器中的流，不能作为数据库运行状态的真相。

本阶段把数据库里的陈旧状态收敛为可重试的失败，并保持前端下一次刷新可以重新读取
稳定状态。它不调用模型，不做正文清理，不修改生产开关。

## 2. 运行状态边界

RAG 状态规则：

pending + age <= recovery_age       -> 保持 pending
pending + age > recovery_age        -> failed / RAG_PROCESS_RESTARTED
completed / failed / stopped        -> 不修改
user 消息                           -> 不修改

默认 RAG_PENDING_RECOVERY_AGE_SECONDS=900。这个值必须大于：

GENERATION_LOCK_TTL_SECONDS + GENERATION_LOCK_CLEANUP_GRACE_SECONDS

当前默认值为 600 + 30 < 900。这样后端不会因为一次普通模型慢响应或停止收尾
而过早把仍可能在运行的任务标记失败。900 秒也与现有额度 reservation 的
15 分钟生命周期对齐，但两者仍是独立模块，不共享数据库状态。

恢复后的消息正文使用稳定的用户可见文案：

> RAG进程中断，本轮回答未正常结束，请重新提问。

不伪造模型回答、不伪造 Token、不删除用户问题和引用。会话 updated_at 会被更新，
因此列表会显示 run_status=idle、last_message_status=failed 和未读状态，用户
可以重新提问。

### Agent

Agent 继续使用已有 AgentRecoveryService：

- pending/running 的 AgentRun 收敛为 failed；
- running 的步骤收敛为 failed；
- pending/streaming 的助手消息收敛为 failed；
- AGENT_PROCESS_RESTARTED 写入 Agent 消息元数据。

本阶段不增加数据库 stopping 状态。停止按钮的瞬时状态仍由取消服务、SSE 事件和
前端 stream registry 负责；如果进程真的退出，已有 Agent 重启恢复会把最终结果置为
失败。这样不会出现“数据库说 stopping、但没有可恢复任务”的悬空状态。

## 3. 实现边界

恢复服务位于：

API dependency -> ConversationRecoveryService -> Message / Conversation -> MySQL transaction

会话路由首次被访问时执行一次恢复，之后由应用进程状态
conversation_recovery_complete 避免每个请求重复扫描。查询只取：

- role == assistant
- status == pending
- created_at <= now - recovery_age

查询使用行锁；提交失败会回滚，应用状态不会被标记为已恢复，下次请求可以再次尝试。
没有后台定时器、没有无限制批量删除、没有读取日志正文，也没有触碰 Agent 表。

应用重启后，各 worker 都可能进行一次扫描。数据库行锁和状态条件保证同一条消息最终
只会收敛一次；前端 registry 的旧流即使晚到，也不能把数据库的 failed 改回 pending。

## 4. 与前端的关系

前端继续以当前会话的 SSE registry 管理 AbortController、草稿和运行标识：

- 新鲜 pending：继续显示正在回答；
- 刷新后发现恢复失败：显示稳定失败文案和可重试状态；
- Agent 的公开执行步骤仍来自后端白名单，不展示隐藏推理；
- 删除保护仍禁止删除真实 pending，恢复后状态变为 failed，才允许删除。

本阶段没有修改前端协议，也不需要新增 SSE 事件。这样可以避免恢复逻辑和 UI 状态
互相写入造成耦合。

## 5. 测试与验收

已通过无费用临时 SQLite 测试：

- 陈旧 pending 助手消息只收敛一次；
- 新鲜 pending 保持运行中；
- completed、failed、stopped 和用户消息不受影响；
- 多用户消息均可恢复，但会话查询仍按用户隔离；
- 恢复后列表为 idle、最后状态为 failed、消息可见为未读；
- recovery age 不得小于等于生成锁 TTL 加收尾余量；
- 原会话 CRUD、问答、SSE 停止/幂等、生成锁和模型重试测试保持通过。

本阶段没有调用 Qwen、Embedding、Reranker 或 SMTP，也没有改变生产模型开关。
发布前完成生产完整备份，只重建 backend；线上 900 秒配置、四容器健康、HTTP 308、
HTTPS 200、未授权 401 和错误日志检查通过。未创建生产测试数据。

## 6. 回滚与后续

回滚只需回退本阶段代码和配置示例；数据库不需要迁移。已被恢复的消息如果回滚代码，
不会自动恢复为 pending，因为失败状态是为了防止刷新后永久等待，且原始模型输出
并未可靠存在，不能凭空恢复。

后续若需要后台任务队列或跨 worker 的统一恢复调度，应单独设计任务租约、批量边界、
监控和幂等，不在 Stage 23 中顺手引入。
