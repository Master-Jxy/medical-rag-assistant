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
