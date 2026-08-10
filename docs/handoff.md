# 当前开发交接

> 最后更新：2026-08-10
> 本文只保留当前事实、工作区边界和一个下一任务。

## 1. 当前真实状态

Stage 25 多模态聊天与输入器升级已完成开发、推送和生产发布。RAG与Agent均支持私有
JPG/PNG/WEBP附件、点击选图、图片粘贴、预览删除、纯图片发送、历史恢复和授权预览。
RAG先形成结构化视觉观察再检索与回答；Agent通过`observe_image`和`inspect_image`
执行每图1次整体观察、最多2次定向补充，并可继续调用公共知识库工具。原图、观察记录、
用量与附件生命周期保持模块化边界，Stage24文档入库视觉Port未被复用。

输入器已改为全宽文本区和底部控制栏；桌面侧栏为220px/收起76px，移动端保持约300px
抽屉。1440、1280、1024和390四视口已完成浏览器验收，收起按钮不再与工作台图标重叠。

生产当前状态：

- GitHub `main`：`95f856d0a470bf9ae3ba5345bdc1b803b97e1c98`。
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
621 passed, 1 skipped, 140 warnings

frontend full suite
20 files / 82 tests passed

SSE parser
PASS

Vite production build
PASS: index-Xv-mGLQX.css / index-CPEwi2bu.js

Alembic temporary roundtrip
0029 -> 0030 -> 0029 -> 0030 PASS

Playwright no-cost browser acceptance
1440x900 / 1280x800 / 1024x768 / 390x844 PASS

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

新窗口先完整阅读`AGENTS.md`和本文。Stage25定向问题再读取：

- `docs/stage25-multimodal-chat-design.md`
- `docs/release-audit-stage25-multimodal-chat.md`
- 对应的media、vision、RAG或Agent单个模块及测试

普通观察期不要全文读取历史技术设计、旧发布审计或大型评估JSON。

## 5. 唯一下一任务

**进入Stage25观察期：只收集真实用户图片失败率、视觉Token成本和前端可用性反馈；发现
明确回归再开定向修复，否则等待Stage26产品决策。**
