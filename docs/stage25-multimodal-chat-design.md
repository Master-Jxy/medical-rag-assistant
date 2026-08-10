# Stage 25 多模态聊天与输入器升级设计

> 日期：2026-08-10
> 状态：设计已确认，已完成本地发布候选
> 目标：在不破坏现有 RAG、Agent、知识库和用量体系的前提下，为 RAG 与 Agent 增加私有图片附件、图片粘贴、结构化视觉观察、按需二次观察和真实多模态模型能力，同时完成侧栏与输入器缺陷修复。

## 1. 产品结果

用户可在 RAG 和 Agent 输入器中点击添加图片或直接粘贴截图，预览后与文字一起发送，也允许只发送图片。图片先通过私有媒体服务校验和存储，再由视觉模型形成结构化观察。RAG 使用观察结果生成检索问题；Agent 将视觉观察作为受控工具结果，并可在信息不足时带明确目标再次观察原图。最终回答继续由现有主模型生成并通过原有 SSE 流式返回。

```text
图片选择或粘贴
-> 前端本地预览与限制检查
-> 私有媒体上传
-> 创建消息并绑定 attachment_ids
-> 视觉首次观察 observe_image
-> 主 Agent / RAG 编排
   -> 信息足够：检索或回答
   -> 信息不足：inspect_image（最多两次定向补充）
   -> 高风险诊疗：安全拒答
-> 最终模型流式回答
-> 用量结算、附件与观察记录持久化
```

第一版限制：JPG、PNG、WEBP；每次最多 3 张；单张最多 10 MiB；单图最多一次整体观察和两次定向观察；自动重试为 0。

## 2. 设计依据

- Dify 将图片作为独立消息文件保存并在模型消息中保留附件，而不是只保存一段描述。
- RAGFlow 对文字密集图片优先 OCR，对普通图片再使用视觉模型，并把派生文本用于检索。
- Docling 将 OCR、版面、表格和图片描述拆成可替换阶段。
- 本项目采用组合方案：原图是私有资产；OCR/视觉观察是可追踪的派生数据；主 Agent 负责决策，不能让第一次图片摘要成为不可恢复的信息瓶颈。

## 3. 架构边界

调用方向保持：

```text
API -> Application Service -> Port / Repository / Infrastructure
```

新增模块：

```text
backend/app/modules/media/
  models.py              # 私有媒体资产和消息附件关系
  schemas.py             # API契约
  repository.py          # MySQL持久化
  storage.py             # 私有文件存储、魔数/尺寸/哈希/EXIF处理
  service.py             # 上传、授权、绑定、删除、清理

backend/app/modules/vision/
  contracts.py           # VisionObservation、VisionModelPort
  policy.py              # 次数、大小、超时、安全与重复目标限制
  service.py             # 首次/定向观察、额度预留与结算
  prompts.py             # 只描述可见事实的结构化Prompt
  routing.py             # general/document/report/diagnostic分类

backend/app/infrastructure/
  dashscope_vision.py    # 真实DashScope多模态适配器
  fake_vision.py         # 无费用测试适配器
```

Stage 24 的 `VisionDocumentPort` 属于知识文档入库链路；Stage 25 的 `VisionChatPort` 属于用户私有聊天链路。两者可复用底层供应商客户端和厂商无关 usage 对象，但不得共享数据库表、权限判断或业务服务。

RAG、Agent、Vue 页面不能直接调用 DashScope SDK，也不能读取服务器文件路径。Agent 工具只接收当前用户已授权的 `media_asset_id`。

## 4. 数据模型与迁移

新增 Alembic `0030_multimodal_chat_assets`：

### 4.1 `media_assets`

- `id`, `user_id`
- `original_name`, `mime_type`, `byte_size`, `width`, `height`
- `sha256`, `storage_key`
- `status`: uploaded / attached / deleted / expired / failed
- `expires_at`, `created_at`, `updated_at`

禁止保存 Base64 和外部公开 URL。`storage_key` 是服务器生成的相对引用，不能接受用户路径。

### 4.2 `message_attachments`

- `id`, `media_asset_id`
- `surface`: rag / agent
- `conversation_id` 或 `agent_message_id`
- `position`, `created_at`

数据库约束保证一个关系只属于一种聊天表面；应用服务再次验证用户所有权。

### 4.3 `vision_observations`

- `id`, `media_asset_id`, `user_id`
- `run_id` 或 `assistant_message_id`
- `kind`: overview / focused / report_extract
- `focus_instruction_hash`，不保存敏感提示正文到普通日志
- `model_name`, `status`, `sequence_no`
- `observation_json`, `input_tokens`, `output_tokens`
- `created_at`, `completed_at`, `error_code`

观察结果属于当前用户私有数据；管理员统计接口只能看到脱敏计量，不读取图片或观察正文。

## 5. 视觉契约

统一返回：

```json
{
  "image_type": "medical_report",
  "summary": "一张血常规检查报告",
  "visible_text": ["白细胞计数", "12.3", "参考范围3.5-9.5"],
  "measurements": [{"name": "白细胞计数", "value": "12.3", "unit": "10^9/L", "reference_range": "3.5-9.5", "flag": "high"}],
  "objects": [],
  "spatial_notes": [],
  "uncertain_content": ["右下角文字模糊"],
  "safety_flags": ["medical_data"]
}
```

视觉模型只能记录图片中可见内容，不诊断、不补写图片外事实、不直接检索知识库。JSON解析失败、空结果或字段超限时按失败处理，不把原始厂商响应暴露给前端。

## 6. Agent执行逻辑

新增工具：

- `observe_image(media_asset_ids, user_question)`：每张图首次整体观察。
- `inspect_image(media_asset_id, focus_instruction)`：信息不足时定向再次观察。
- 后续可增加 `extract_medical_report`，第一版可由统一观察结构承载。

Agent状态增加附件ID、已完成观察、观察次数和目标哈希。图执行节点进入现有公开计划/工具事件，但不展示隐藏推理、供应商Prompt或图片文件路径。

```text
prepare_message
-> ensure_overview_observation
-> plan
-> execute_tool
   -> search_knowledge
   -> observe_image
   -> inspect_image
-> plan（循环）
-> safety_finalize
-> persist_and_stream
```

循环限制：每图最多 3 次视觉调用；定向观察最多 2 次；相同目标不得重复；连续空结果或相同结果立即停止；达到上限后要求用户上传更清晰图片。停止生成、断连和后台恢复继续沿用 Stage 23 的 run/pending 恢复机制。

## 7. RAG执行逻辑

RAG图片消息先完成整体观察，再由专用查询构造器使用“用户问题 + 关键可见文字 + 异常指标”生成干净检索问题。完整 OCR 噪声不直接塞入向量检索。知识库来源和图片观察必须分开显示：知识库片段可以作为引用，视觉观察只能标记为“图片识别结果”。

第一版 RAG 不执行多轮 `inspect_image` 循环；若首次观察不足，明确提示用户改用 Agent 或上传清晰图片。Agent承担复杂循环，避免两套编排逻辑重复。

## 8. 真实供应商与配置

新增非秘密配置：

```text
VISION_CHAT_ENABLED=false
VISION_PROVIDER=dashscope
VISION_MODEL=qwen3-vl-plus
VISION_MAX_IMAGES=3
VISION_MAX_IMAGE_BYTES=10485760
VISION_MAX_CALLS_PER_IMAGE=3
VISION_TIMEOUT_SECONDS=45
VISION_AUTOMATIC_RETRIES=0
MEDIA_RETENTION_DAYS=30
```

复用现有 `DASHSCOPE_API_KEY` 注入，不新增或提交密钥。生产启用前先使用 Fake 完成全量测试，再使用一张无敏感测试图做一次受控真实调用。模型不可用时文字聊天必须继续正常，图片消息返回明确的可重试错误。

## 9. 用量、额度与幂等

- 图片上传本身不计模型Token。
- 每次视觉调用先通过现有 `QuotaGatePort` 预留，拿到实际 usage 后结算，失败释放余额。
- usage surface 使用 `vision_rag` / `vision_agent`，并通过同一个 assistant message / run group 聚合展示。
- idempotency key 必须包含用户、会话、附件ID、观察种类和目标哈希，网络重放不能重复收费。
- 前端显示视觉调用与最终回答的总输入/输出Token；供应商不返回计量时诚实显示未知。

## 10. 安全和医疗边界

- 服务端校验扩展名、MIME、魔数、Pillow结构、像素数和解压炸弹风险。
- 解码后重新编码为规范PNG/JPEG/WEBP并去除EXIF；禁止SVG、GIF、TIFF和远程URL上传。
- 普通用户只能读取自己的附件；下载接口使用授权检查和不可猜测ID。
- 图片、Base64、OCR正文、观察正文不写日志。
- 长期记忆不得自动保存图片中的健康信息；仍需用户确认。
- CT、X光、MRI、病理等只允许描述可见信息和解释已有报告，禁止确定诊断、处方和治疗结论。
- 非医学图片继续遵循当前产品边界；系统说明和普通识图可回答，明显无关复杂任务由路由策略拒答。

## 11. 前端输入器与侧栏

RAG 和 Agent 共享图片草稿 composable / 组件：选择、粘贴、预览、删除、校验、上传、重试、对象URL释放。禁止复制两套附件状态机。

输入器结构统一：

```text
图片缩略图与上传状态（按需）
全文宽 textarea（一行起步，最多四行）
底部工具栏：左侧添加图片；右侧模型、字数、停止/发送
```

支持 `paste` 事件读取 `clipboardData.items` 中的图片；普通文本粘贴保持浏览器默认行为。图片可以单独发送；发送成功后清空附件，失败时保留草稿供重试。

UI修复：

- 桌面展开侧栏固定约 220px，收起侧栏保持 76px；移动端抽屉保持适合触控的宽度。
- 收起按钮取消绝对定位，Logo、展开按钮、第一条导航使用正常布局，杜绝与“工作台”重叠。
- `aria-expanded`、键盘焦点、移动端抽屉行为保持正确。
- 输入器空态也让textarea占满整行，模型与发送按钮放到底部。

## 12. 开发任务

1. **25.0 基线与契约**：锁定接口、受保护auth哈希、迁移头、Fake测试边界。
2. **25.1 私有媒体资产**：迁移、上传、授权读取、删除/过期、存储安全。
3. **25.2 视觉端口与供应商**：结构化契约、Fake/Disabled、DashScope适配器、配置工厂。
4. **25.3 RAG图片消息**：附件绑定、首次观察、检索查询、SSE与历史恢复。
5. **25.4 Agent视觉循环**：工具、LangGraph状态、二次观察限制、停止与恢复。
6. **25.5 前端输入器**：选择/粘贴/预览/重试、全宽输入、底部工具栏，RAG/Agent一致。
7. **25.6 侧栏修复**：220px展开宽度、76px收起布局、无重叠和响应式检查。
8. **25.7 用量与安全**：额度、幂等、隐私、拒答、自动清理和管理员脱敏统计。
9. **25.8 发布候选**：后端/前端全量测试、迁移往返、真实单次视觉验收、浏览器桌面/移动截图、备份/部署/健康检查。

每个任务单独提交；不得修改、提交、回退或覆盖现有 `backend/app/modules/auth/service.py` 用户改动。

## 13. 验收标准

- RAG和Agent均支持点击选图、Ctrl+V粘贴截图、图片预览/删除及单图发送。
- 普通文本粘贴不受影响；超数量、超大小、伪造MIME和越权访问被拒绝。
- 首次观察进入主Agent；信息不足时可定向二次观察，次数和重复目标限制生效。
- 图片问答可调用知识库并区分“图片观察”和“知识库引用”。
- 停止、重连、跨页面恢复、历史回放和删除会话不留下错误附件引用。
- 文字聊天在视觉供应商关闭或故障时不回归。
- 输入器全文宽、按钮位于底部、1至4行稳定增高；侧栏收起无重叠，展开宽度符合参考图。
- 1440x900、1280x800、1024x768、390x844 无白屏、明显溢出或遮挡。
- 全量测试、迁移 `0029 -> 0030 -> 0029 -> 0030`、生产构建和安全扫描通过。
- 推送前工作区只允许保留受保护auth改动；部署前完成生产备份，部署后四容器healthy、迁移head正确、HTTP/HTTPS和无费用主路径通过。
