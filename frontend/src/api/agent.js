import http, { apiBaseUrl, createApiErrorFromResponse } from './http.js'
import { getAuthorizationHeaders, notifyUnauthorized } from '../auth/token.js'

export async function createAgentThread(title = '新对话', assistantMode = 'general') {
  return (await http.post('/agent/threads', {
    title,
    assistant_mode: assistantMode,
  })).data
}

export async function listAgentThreads(status = 'active') {
  return (await http.get('/agent/threads', {
    params: { status, offset: 0, limit: 100 },
  })).data
}

export async function getAgentThread(threadId) {
  return (await http.get(`/agent/threads/${encodeURIComponent(threadId)}`)).data
}

export async function markAgentThreadRead(threadId, lastReadSequence) {
  return (await http.post(
    `/agent/threads/${encodeURIComponent(threadId)}/read`,
    { last_read_sequence: lastReadSequence },
  )).data
}

export async function updateAgentThread(threadId, changes) {
  return (await http.patch(
    `/agent/threads/${encodeURIComponent(threadId)}`,
    changes,
  )).data
}

export async function deleteAgentThread(threadId) {
  return (await http.delete(`/agent/threads/${encodeURIComponent(threadId)}`)).data
}

export async function listAgentMessages(threadId, limit = 100) {
  return (await http.get(
    `/agent/threads/${encodeURIComponent(threadId)}/messages`,
    { params: { offset: 0, limit } },
  )).data
}

export async function listAgentRuns(limit = 20) {
  const response = await http.get('/agent/runs', { params: { offset: 0, limit } })
  return response.data
}

export async function getAgentRun(runId) {
  const response = await http.get(`/agent/runs/${encodeURIComponent(runId)}`)
  return response.data
}

export async function stopAgentRun(runId) {
  const response = await http.post(`/agent/runs/${encodeURIComponent(runId)}/stop`)
  return response.data
}

export async function downloadAgentArtifact(artifactId) {
  const response = await fetch(
    `${apiBaseUrl}/agent/artifacts/${encodeURIComponent(artifactId)}/download`,
    { headers: { ...getAuthorizationHeaders() } },
  )
  if (!response.ok) {
    if (response.status === 401) notifyUnauthorized()
    throw await createApiErrorFromResponse(response)
  }
  return response.blob()
}

function userError(message) {
  const error = new Error(message)
  error.userMessage = message
  return error
}

function parseFrame(frame) {
  let event = 'message'
  const lines = []
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    if (line.startsWith('data:')) lines.push(line.slice(5).trimStart())
  }
  if (!lines.length) return null
  return { event, data: JSON.parse(lines.join('\n')) }
}

function dispatch(item, handlers) {
  if (!item) return
  handlers.onEvent?.(item.event, item.data)
  if (item.event === 'error') {
    throw userError(item.data.message || 'Agent运行失败。')
  }
}

export async function streamAgentRun(runId, handlers = {}) {
  return streamAgentEndpoint(
    `/agent/runs/${encodeURIComponent(runId)}/stream`,
    { handlers },
  )
}

export async function streamAgentMessage(
  threadId,
  payload,
  idempotencyKey,
  handlers = {},
) {
  return streamAgentEndpoint(
    `/agent/threads/${encodeURIComponent(threadId)}/messages/stream`,
    {
      payload,
      idempotencyKey,
      handlers,
    },
  )
}

export async function retryAgentMessage(
  messageId,
  idempotencyKey,
  handlers = {},
) {
  return streamAgentEndpoint(
    `/agent/messages/${encodeURIComponent(messageId)}/retry`,
    { idempotencyKey, handlers },
  )
}

async function streamAgentEndpoint(
  path,
  { payload, idempotencyKey, handlers = {} },
) {
  const headers = { ...getAuthorizationHeaders() }
  if (payload) headers['Content-Type'] = 'application/json'
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey
  const response = await fetch(`${apiBaseUrl}${path}`, {
    method: 'POST',
    headers,
    body: payload ? JSON.stringify(payload) : undefined,
    signal: handlers.signal,
  })
  if (!response.ok) {
    if (response.status === 401) notifyUnauthorized()
    throw await createApiErrorFromResponse(response)
  }
  if (!response.body) throw userError('浏览器不支持读取流式响应。')

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  const cancel = () => reader.cancel().catch(() => {})
  handlers.signal?.addEventListener('abort', cancel, { once: true })
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
      const frames = buffer.split(/\r?\n\r?\n/)
      buffer = frames.pop() || ''
      for (const frame of frames) dispatch(parseFrame(frame), handlers)
      if (done) break
    }
    if (buffer.trim()) dispatch(parseFrame(buffer), handlers)
  } finally {
    handlers.signal?.removeEventListener('abort', cancel)
  }
}
