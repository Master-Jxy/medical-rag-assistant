import http, { apiBaseUrl, createApiErrorFromResponse } from './http.js'
import { consumeSseResponse } from './chat.js'
import { getAuthorizationHeaders, notifyUnauthorized } from '../auth/token.js'
import { createUuid } from '../utils/uuid.js'

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

export async function stopConversationStream(conversationId, idempotencyKey) {
  const response = await http.post(
    `/conversations/${conversationId}/chat/stop`,
    null,
    { headers: { 'Idempotency-Key': idempotencyKey } },
  )
  return response.data
}

export async function streamConversation(conversationId, question, options = {}) {
  const idempotencyKey = options.idempotencyKey || createUuid()
  const response = await fetch(
    `${apiBaseUrl}/conversations/${encodeURIComponent(conversationId)}/chat/stream`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': idempotencyKey,
        ...getAuthorizationHeaders(),
      },
      body: JSON.stringify({ question, top_k: options.topK || 4 }),
      signal: options.signal,
    },
  )

  if (!response.ok) {
    if (response.status === 401) notifyUnauthorized()
    throw await createApiErrorFromResponse(response)
  }

  await consumeSseResponse(response, options)
}
