# Platform v1.5 阶段16生产发布审计

> 发布日期：2026-07-29
> 状态：代码、迁移、配置与无费用生产验收完成

## 1. 发布范围

- 邮箱验证码注册与密码重置，密码重置后旧JWT失效。
- 旧测试账号只读预检与受控维护命令。
- 普通RAG和Agent实际Token计量、unknown语义与脱敏用量账本。
- 登录、注册验证码、密码重置和运行统计前端。
- `0020_email_account_lifecycle`和`0021_model_usage_records`。

没有修改RAG检索策略、Prompt、知识审核规则、Agent工具、公共知识数据或现有SSE正文
协议。

## 2. Git与备份

- 应用提交：`a9d43c8`
- 格式修正：`c4f8939`
- 发布前生产提交：`87b0490`
- 发布前备份：`backup-20260729T042645Z`
- 备份七类SHA-256全部通过，目录权限700、文件权限600。

## 3. 迁移与运行状态

- Alembic从`0019_agent_message_order`升级到单一
  `0021_model_usage_records (head)`。
- backend、web、MySQL、Redis四容器均healthy。
- HTTPS健康及首页200，HTTP固定308。
- 生产前端包与本地正式构建SHA-256一致。

## 4. 数据一致性

发布前后核心数量一致：

- 用户12，文档25，已发布文档24，提交27，版本25。
- 普通会话7、消息120。
- Agent thread 3、message 26、run 13、step 4。
- Chroma 94片段、上传文件25、隔离提交文件2、Redis 9键。
- 新模型用量账本0条。

## 5. 安全闸门

本次没有发送真实SMTP、创建或重置生产账号、执行生产测试账号清理，也没有调用真实
Qwen、Embedding或Reranker。真实SMTP、账号清理和真实模型计量仍分别需要新的明确授权。

完整命令、验证数量和当前唯一下一任务见
[`docs/handoff.md`](handoff.md)。
