# Medical RAG Frontend

医疗知识库智能问答系统的 Vue 3 前端。

## 本地启动

```powershell
npm install
npm run dev
```

默认访问 `http://localhost:5173`。启动前请确保 FastAPI 运行在 `http://127.0.0.1:8000`。

前端只请求 FastAPI，不能配置或保存 `DASHSCOPE_API_KEY`。

当前页面：

- `/`：系统概览和后端健康状态。
- `/chat`：SSE 流式知识库问答、停止生成和引用来源展开。
- `/knowledge`：PDF/TXT 上传、文档列表和删除管理。
