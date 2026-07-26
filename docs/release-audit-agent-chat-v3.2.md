# Agent Chat v3.2 发布审计

> 发布日期：2026-07-27  
> 业务提交：`1b6698f7848de9b4728051a6f593d45cf74cb725`  
> 生产迁移：`0019_agent_message_order (head)`

## 1. 发布范围

- 后端新增安全的公开`decision`事件，不暴露或保存隐藏推理。
- 前端将计划、工具选择、工具结果和检查结果组成可折叠执行时间线。
- Agent聊天气泡、引用来源、输入区与RAG页面保持同一视觉语言。
- 删除或切换会话时同步清理当前run、时间线、引用与详情状态。
- 未新增数据库迁移、Agent工具、写操作或模型预算。

## 2. 发布前验证

- 后端：347项测试通过。
- 前端：10个测试文件、39项测试通过。
- Vite正式构建、SSE UTF-8解析、`pip check`和`git diff --check`通过。
- 生产包扫描：包含同源`/api/v1`，不含`127.0.0.1:8000`。

## 3. 备份与回滚

- 完整备份：`/home/deploy/medical-rag-backups/backup-20260726T162016Z`
- MySQL、app_data、Chroma、Redis、`deploy/.env`、Compose和清单校验均为OK。
- 回滚镜像：`medical-rag-backend:rollback-b5a37d3`、
  `medical-rag-web:rollback-b5a37d3`。
- 发布前前端目录：
  `/home/deploy/release-assets/frontend-dist-b5a37d3-pre-v32`

备份脚本的数据导出和校验成功；最初保留策略因历史目录归属root返回非零，修正旧目录
归属后继续发布。该非零不是备份内容损坏。

## 4. 部署过程

- GitHub推送成功。
- 服务器直连GitHub发生TLS接收中断，因此使用本地生成的完整Git bundle，在服务器
  执行`fetch`和`merge --ff-only`更新到业务提交；没有强制覆盖或改写历史。
- 只构建并重建backend、web；MySQL、Redis未重建，数据卷未删除。
- 四个容器最终均为healthy。
- 首次Web构建误用了服务器上的旧`v3.1`静态目录，用户截图中的版本标签帮助发现该
  问题。随后重新上传本地已验证的`v3.2`正式产物，使用`--no-cache`只重建Web容器；
  最终公网首页引用`index-DmAMgtUm.js`，包内标签为`AGENT CHAT V3.2`。后端、
  MySQL、Redis和业务数据未受此次纠偏影响。

## 5. 线上验证

- HTTPS健康接口返回200；HTTP固定返回308并跳转HTTPS。
- Alembic保持单头`0019_agent_message_order`。
- 公网首页下发新版JS/CSS资源。
- Unicode JSON“你好”走确定性0工具路线，SSE包含`message_created`和
  `message_completed`，没有`error`；持久化消息顺序为user、assistant，状态均为
  completed。

第一次自动请求由Windows PowerShell错误地把中文编码为`??`，因此没有命中确定性
问候，进入Qwen规划启动路径后失败。系统记录Token 0、估算费用0，但不能据此断言
供应商侧绝对未计费。之后未继续进行任何需要模型的验收。

## 6. 清理与边界

- 临时账号：0
- 临时thread：0
- 临时message：0
- 临时run：0
- 未上传、删除或修改知识文档和Chroma数据。
- 自动浏览器没有建立有效生产页面会话，因此未把1440、1280、390宽度的线上点击与
  观感检查写成通过；该项由用户实际浏览器补充。

## 7. 零工具状态显示热修复

用户实测发现`你是谁呢`和`介绍一下自己`没有命中原先仅覆盖`你是谁`的确定性身份
问答，转入模型规划后失败；同时前端只根据“零步骤”显示“直接回答”，导致同一个气泡
上方显示处理完成、正文却显示任务失败。

- 后端扩充问候、身份、能力与正面反馈的确定性短语，均不调用模型和工具。
- 前端执行过程同时读取run/message终态；failed、stopped与completed分别展示，
  只有completed且零步骤才显示“直接回答”。
- 后端完整测试353项、前端10个文件40项、SSE解析、Vite构建、`pip check`和
  `git diff --check`通过。
- 发布前备份：
  `/home/deploy/medical-rag-backups/backup-20260726T164852Z`，全部SHA-256校验通过。
- 修复提交：`fe40ecd`；仅重建backend和web，MySQL与Redis未重建。
- 线上Unicode验收在同一临时thread依次发送`你是谁呢`和`介绍一下自己`，两轮均为
  HTTP 200、completed、0 step、0 Token、0估算费用且无SSE error。
- 验收临时账号、thread、message、run和Redis键均清理为0；四个容器healthy，
  Alembic保持`0019_agent_message_order (head)`。

## 8. 模型非工具路由兼容修复

真实用户问题`我最近一直头疼`在模型规划阶段被正确路由为安全拒绝，但Qwen返回
`"plan": null`；原`PlanDecision`要求列表，导致Pydantic校验失败并被外层统一记录为
`AGENT_EXECUTION_FAILED`。同类问题会影响不需要工具的直接回答、澄清和拒绝路由。

- `PlanDecision`在输入校验阶段把`plan: null`规范化为`[]`，仍保留最多5项公开计划
  和严格额外字段检查。
- 新增direct_reply、clarification、refuse三类回归用例；后端356项、前端40项、
  SSE解析、Vite正式构建、`pip check`和`git diff --check`全部通过。
- 发布前备份：
  `/home/deploy/medical-rag-backups/backup-20260726T171557Z`，全部SHA-256校验通过。
- 修复提交：`993472c`；仅重建backend，web、MySQL、Redis和数据卷未重建。
- 线上同一临时thread真实调用`qwen3-max`验证三轮：
  - `测试`：返回具体医学资料任务的澄清提示。
  - `讲一下辛亥革命`：正常说明超出医学资料处理范围。
  - `我最近一直头疼`：正常触发不诊断、不提供医疗建议的安全边界。
- 三轮均为completed、0 step、无SSE error，共987 Token，估算费用约¥0.00352；
  临时账号、thread、message、run和Redis键清理后均为0，四个容器healthy。

## 9. 输入框自动聚焦交互

- `AgentComposer`只暴露受disabled状态约束的`focus()`界面能力，不让会话API或SSE
  解析器直接操作DOM。
- Agent页面在首次加载、新建会话、切换历史会话以及发送/重试流收尾并恢复服务端状态后，
  通过下一次Vue渲染周期聚焦输入框。
- 新增真实DOM焦点回归用例，覆盖新建、切换和模型回复结束三个场景。
- 前端10个测试文件41项、SSE UTF-8解析、Vite正式构建和`git diff --check`通过。
- 交互提交：`df407a9`；本次只需替换Web静态包并重建web容器，不调用模型，不修改
  后端、MySQL、Redis、迁移或业务数据。
