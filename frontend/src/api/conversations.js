import http, { apiBaseUrl } from './http.js'
import { consumeSseResponse } from './chat.js'

export async function listConversations(limit = 50) {
  const response = await http.get('/conversations', { params: { limit, offset: 0 } })
  return response.data
}

export async function createConversation(title = '新对话') {
  const response = await http.post('/conversations', { title })
  return response.data
}

export async function getConversation(conversationId) {
  const response = await http.get(`/conversations/${conversationId}`)
  return response.data
}

export async function deleteConversation(conversationId) {
  const response = await http.delete(`/conversations/${conversationId}`)
  return response.data
}

function createUserError(message) {
  const error = new Error(message)
  error.userMessage = message
  return error
}

export async function streamConversation(conversationId, question, options = {}) {
  const response = await fetch(
    `${apiBaseUrl}/conversations/${encodeURIComponent(conversationId)}/chat/stream`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, top_k: options.topK || 4 }),
      signal: options.signal,
    },
  )

  if (!response.ok) {
    let message = `请求失败（HTTP ${response.status}）`
    try {
      const data = await response.json()
      message = data?.error?.message || data?.detail?.[0]?.msg || data?.detail || message
    } catch {
      // 非 JSON 错误响应使用上面的通用信息。
    }
    throw createUserError(message)
  }

  await consumeSseResponse(response, options)
}
