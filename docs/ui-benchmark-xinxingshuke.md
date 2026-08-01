# 新星数科 UI 对标记录

## 研究范围

本记录只提炼 `https://xinxingshuke.com/` 控制台与 AI 对话页的布局和交互思想，不复制品牌、文案或业务数据。相关截图仅保存在本机忽略目录：

- `reference/ui-research/xinxingshuke/dashboard-usage.png`
- `reference/ui-research/xinxingshuke/console-reference.png`
- `reference/ui-research/xinxingshuke/chat-workspace-reference.png`
- `reference/ui-research/layout-fix/rag-desktop-1440.png`
- `reference/ui-research/layout-fix/rag-mobile-390.png`
- `reference/ui-research/layout-fix/agent-desktop-1440.png`
- `reference/ui-research/layout-fix/agent-mobile-390.png`

`reference/` 不进入 Git，截图不得包含或传播余额、请求标识和账号信息。

## 可借鉴的界面思想

### 控制台

- 左侧导航保持稳定，主内容使用浅灰画布和白色业务面板。
- 顶部先展示少量关键指标，再展示趋势、明细和快捷入口，信息层级清楚。
- 数据强调使用操作蓝，状态仍使用成功、警告和危险色，不让整页被单一颜色覆盖。
- 表格和图表属于主内容区，窄屏时只让局部容器滚动。

### AI 对话

- 全局导航、会话列表、消息区和输入器是四个独立区域。
- 消息变长时只滚动消息区，会话列表和底部输入器不跟随页面移动。
- 对话正文限制最大宽度并居中，减少超长行，输入器与正文宽度保持一致。
- 新建会话、历史、附件或技能等操作靠近输入器，但不挤入消息气泡。
- Token 与执行信息紧贴对应回答，来源和过程按需展开，默认保持聊天主线安静。

## 本项目采用方式

- RAG 和 Agent 继续复用现有企业控制台外壳与视觉变量，不另建一套主题。
- 顶栏以下的流式工作区固定为当前可视高度，浏览器页面不承担长消息滚动。
- RAG 会话栏独立滚动，消息区独立滚动，输入器固定在聊天面板底部。
- Agent 会话栏独立稳定，`AgentConversation` 继续作为唯一消息滚动容器，绝对定位的 Composer 保持在面板底部。
- 移动端保留抽屉式会话列表，消息区继承剩余工作区高度，不重复使用视口高度公式。

## 后续前端升级边界

- 可以继续借鉴控制台的信息层级、聊天正文宽度和局部滚动策略。
- 不照搬对方品牌色、Logo、文案、积分体系或具体组件代码。
- 每次升级都验收 1440、900 和 390 三种宽度，重点检查页面级滚动、输入器位置、历史栏位置、文字溢出和移动端抽屉。
