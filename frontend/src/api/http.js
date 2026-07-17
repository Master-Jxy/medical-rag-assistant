import axios from 'axios'

import { getAccessToken, notifyUnauthorized } from '../auth/token.js'

// 前端只访问 FastAPI，不保存也不接触阿里云模型密钥。
export const apiBaseUrl =
  import.meta.env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api/v1'

const http = axios.create({
  baseURL: apiBaseUrl,
  timeout: 60000,
})

http.interceptors.request.use((config) => {
  const token = getAccessToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401 && getAccessToken()) notifyUnauthorized()
    return Promise.reject(error)
  },
)

export default http

const apiErrorMessages = {
  AUTH_RATE_LIMITED: '登录尝试过于频繁，请稍后再试。',
  CHAT_RATE_LIMITED: '提问过于频繁，请稍后再试。',
  UPLOAD_RATE_LIMITED: '上传过于频繁，请稍后再试。',
  UPLOAD_CONCURRENCY_LIMITED: '当前已有文件正在处理，请等待完成后再上传。',
  CONVERSATION_GENERATION_IN_PROGRESS: '当前会话正在生成回答，请等待完成后再试。',
  IDEMPOTENCY_REQUEST_IN_PROGRESS: '这次提问仍在处理中，请稍候，不要重复发送。',
  IDEMPOTENCY_KEY_REUSED: '请求状态已经变化，请重新发送这条问题。',
  GENERATION_LOCK_UNAVAILABLE: '问答保护服务暂时不可用，请稍后重试。',
  IDEMPOTENCY_UNAVAILABLE: '问答保护服务暂时不可用，请稍后重试。',
}

function messageFromPayload(data, status) {
  const errorCode = data?.error?.code
  if (errorCode && apiErrorMessages[errorCode]) return apiErrorMessages[errorCode]
  if (data?.error?.message) return data.error.message
  if (typeof data?.detail === 'string') return data.detail
  if (Array.isArray(data?.detail) && data.detail[0]?.msg) return data.detail[0].msg
  if (status === 429) return '操作过于频繁，请稍后再试。'
  if (status === 409) return '当前操作仍在处理中，请稍后再试。'
  if (status === 503) return '服务暂时不可用，请稍后重试。'
  return `请求失败（HTTP ${status}）`
}

export function createApiError(data, status) {
  const message = messageFromPayload(data, status)
  const error = new Error(message)
  error.userMessage = message
  error.status = status
  error.errorCode = data?.error?.code || ''
  error.requestId = data?.request_id || ''
  return error
}

export async function createApiErrorFromResponse(response) {
  let data = null
  try {
    data = await response.json()
  } catch {
    // 非 JSON 响应根据状态码给出稳定提示。
  }
  return createApiError(data, response.status)
}

export function getApiErrorMessage(error) {
  if (error?.name === 'AbortError') return '已停止生成。'
  if (error?.userMessage) return error.userMessage
  const data = error?.response?.data
  if (data) return messageFromPayload(data, error?.response?.status)
  if (error?.code === 'ECONNABORTED') return '请求超时，请稍后重试。'
  return '无法连接后端服务，请确认 FastAPI 已启动。'
}
