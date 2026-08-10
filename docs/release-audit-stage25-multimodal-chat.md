# Stage 25 多模态聊天生产发布审计

> 日期：2026-08-10
> 范围：Stage 25.1～25.8 开发、验证、生产发布与真实视觉烟测
> 结论：PASS；GitHub 与生产均为 `95f856d`，生产迁移为 `0030`

## 1. 交付结论

Stage 25 已在模块化单体边界内完成。RAG 与 Agent 共享私有媒体资产和聊天视觉 Port，
但继续使用独立路由、应用用例、SSE 和页面状态；Stage 24 文档入库视觉 Port 未被复用。
自动化继续使用 Fake/Disabled 适配器；生产显式启用 DashScope
`qwen3-vl-plus`，自动重试固定为0。本审计包含生产发布证明。

本地提交：

| 提交 | 内容 | 状态 |
|---|---|---|
| `a7a15f2` | 私有媒体资产与0030迁移 | PASS |
| `c894329` | 结构化聊天视觉边界 | PASS |
| `9a128cd` | RAG图片消息链路 | PASS |
| `6fbe243` | Agent受控图片工具 | PASS |
| `d6d86b9` | 共享附件输入器与侧栏修复 | PASS |
| `265f111` | 会话附件生命周期 | PASS |
| `364ecd2` | 清理和旧回归边界加固 | PASS |
| `9a2f448`～`5511418` | 真实模型预检、Compose视觉配置与价格归一化 | PASS |
| `95f856d` | 兼容DashScope对象型字段漂移并增加回归测试 | PASS |

上述提交均已推送 GitHub `main` 并快进部署到生产。

## 2. 功能与安全矩阵

| 项目 | 结果 | 证据摘要 |
|---|---|---|
| JPG/PNG/WEBP、3张、10MiB | PASS | 前后端校验与媒体测试 |
| MIME伪造、路径穿越、像素炸弹、EXIF | PASS | 解码后规范重编码；安全测试 |
| 私有上传、Bearer预览、草稿删除 | PASS | owner/other隔离与文件删除测试 |
| 会话/线程删除和孤儿清理 | PASS | RAG、Agent和cleanup测试 |
| 0030 三表与回滚 | PASS | 0029→0030→0029→0030临时SQLite |
| `VisionChatPort` 与结构化观察 | PASS | Fake/Disabled及契约测试 |
| DashScope真实适配器 | PASS | `qwen3-vl-plus` 生产真实调用返回结构化观察、actual Token和请求ID；对象型字段漂移已归一化 |
| 视觉用量与额度 | PASS | actual结算、失败释放、幂等不重复计费 |
| RAG纯图片、观察、检索、SSE、历史 | PASS | Stage25 RAG focused tests |
| Agent overview/inspect与知识库继续调用 | PASS | Stage25 Agent focused tests |
| 每图1+2、总计3、目标去重、相同结果停止 | PASS | 视觉策略测试 |
| 点击选图、图片粘贴、普通文字粘贴 | PASS | 共享草稿组件测试与浏览器选图 |
| 上传失败重试、删除、纯图片发送 | PASS | 组件测试；浏览器确认纯图片按钮启用 |
| 医疗可见事实/非诊断边界 | PASS | Prompt、结构化观察与UI提示测试 |
| 私有历史预览 | PASS | Authorization blob请求实现与组件回归 |
| 输入器与侧栏布局 | PASS | 四视口浏览器截图和收起/抽屉交互 |

## 3. 自动化验证

```text
backend\.venv\Scripts\python.exe -m pytest -q backend\tests
621 passed, 1 skipped, 140 warnings

D:\Nodejs\npm.cmd --prefix frontend test
20 files, 82 tests passed

D:\Nodejs\npm.cmd --prefix frontend run test:stream
SSE parser test passed

D:\Nodejs\npm.cmd --prefix frontend run build
PASS: index-Xv-mGLQX.css / index-CPEwi2bu.js

Stage25 focused lifecycle/vision/RAG/Agent/recovery matrix
25 passed

Python compile/import
PASS，受保护 auth service 排除；6个关键模块导入通过

Alembic temporary SQLite
upgrade 0029 PASS
upgrade 0030 PASS
downgrade 0029 PASS
upgrade 0030 PASS

git diff --check
PASS（仅Windows CRLF提示）

protected auth SHA256
9468793F2264CD89F859F149BB72B7DCA5D7941805A66E13D4CDAF6DDF7BA9B0
```

全量后端最终从仓库根目录执行通过：621 passed，另有1项既有skip。供应商格式漂移
回归覆盖Markdown JSON围栏、单字符串列表字段、对象型`objects`和数值测量字段。

## 4. 浏览器验收

使用 Playwright CLI、项目本地 Vite 和无费用静态 API mock；未启动真实后端或供应商。

| 视口 | 页面 | 结果 |
|---|---|---|
| 1440×900 | RAG、桌面展开/收起 | PASS |
| 1280×800 | RAG | PASS |
| 1024×768 | RAG响应式 | PASS |
| 390×844 | RAG、Agent、移动抽屉 | PASS |

检查项包括：输入器不遮挡、textarea占满整行、工具栏左右分组、附件预览与删除、纯图片
发送按钮启用、桌面220px/76px侧栏、收起按钮无重叠、约300px移动抽屉和控制台0 error。

限制：浏览器未连接完整FastAPI，因此真实上传提交、SSE停止/恢复和上传失败重试不记为
浏览器端到端PASS；这些行为由Fake后端/前端自动化覆盖。页面显示的“无法连接后端”是该
隔离验收的预期降级状态，不是生产健康结论。

## 5. 隐私、成本与清理

- 未读取 `.env`、密钥、生产上传、Chroma、备份或正文日志。
- 仅调用真实 DashScope 视觉做发布前最小验收；未调用 Embedding、Reranker、OCR、SMTP 或网页抓取。
- 真实视觉使用一张非医疗 UI 截图；不输出密钥、图片正文或完整提示词。
- 视觉账本只保存脱敏ID、模型、Token、价格快照和稳定错误码，不保存图片、问题或观察正文。
- 临时迁移数据库已删除；Playwright会话和Vite进程已关闭。
- `backend/data/media/` 已忽略，不提交运行图片。
- 演示账号维护若发现私有媒体但未注入存储适配器会拒绝执行。

## 6. 发布闸门

| 动作 | 状态 | 总控要求 |
|---|---|---|
| 真实视觉最小验收 | PASS | `qwen3-vl-plus` 返回结构化观察；请求ID存在 |
| Git push | PASS | GitHub `main` 为 `95f856d` |
| 生产备份 | PASS | `backup-20260810T003429Z`，7项SHA-256全部通过 |
| 生产0030迁移 | PASS | `0030_multimodal_chat_assets (head)` |
| backend/web发布 | PASS | Stage25全量先发布；格式兼容修复仅无依赖重建backend，数据卷未改 |
| HTTP/HTTPS/健康/SSE验收 | PASS | HTTP 308；HTTPS首页与健康接口200；生产静态资产匹配本地候选 |
| 回滚准备 | PASS | 保留外置完整备份、前一提交`5511418`及现有恢复脚本；未执行破坏性恢复 |

## 7. 生产发布证据

- 生产提交：`95f856d0a470bf9ae3ba5345bdc1b803b97e1c98`，工作区干净。
- 备份：`/home/deploy/medical-rag-backups/backup-20260810T003429Z`，SHA-256校验通过。
- 迁移：`0030_multimodal_chat_assets (head)`。
- 容器：backend、web、mysql、redis均为healthy。
- 网络：HTTP 308；HTTPS首页和`/api/v1/health`均为200。
- 静态资产：`index-CPEwi2bu.js`、`index-Xv-mGLQX.css`。
- 视觉配置：enabled、DashScope、`qwen3-vl-plus`、automatic retries 0。
- 生产无持久化烟测：`production_vision=PASS`，311输入Token、155输出Token、466总Token，measurement为actual，请求ID存在；近15分钟后端错误标记为0。

## 8. 唯一下一任务

**进入Stage25观察期：只收集真实用户图片失败率、视觉Token成本和前端可用性反馈；发现明确回归再开定向修复，否则等待Stage26产品决策。**
