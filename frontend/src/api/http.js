import axios from 'axios'

// 前端只访问 FastAPI，不保存也不接触阿里云模型密钥。
export const apiBaseUrl =
  import.meta.env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api/v1'

const http = axios.create({
  baseURL: apiBaseUrl,
  timeout: 60000,
})

export default http

export function getApiErrorMessage(error) {
  if (error?.name === 'AbortError') return '已停止生成。'
  if (error?.userMessage) return error.userMessage
  const data = error?.response?.data
  if (data?.error?.message) return data.error.message
  if (typeof data?.detail === 'string') return data.detail
  if (Array.isArray(data?.detail) && data.detail[0]?.msg) return data.detail[0].msg
  if (error?.code === 'ECONNABORTED') return '请求超时，请稍后重试。'
  return '无法连接后端服务，请确认 FastAPI 已启动。'
}
