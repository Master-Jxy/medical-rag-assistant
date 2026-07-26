import http, { apiBaseUrl, createApiErrorFromResponse } from './http.js'
import { getAuthorizationHeaders, notifyUnauthorized } from '../auth/token.js'

export async function createAgentRun(task) {
  const response = await http.post('/agent/runs', { task })
  return response.data
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
  const response = await fetch(
    `${apiBaseUrl}/agent/runs/${encodeURIComponent(runId)}/stream`,
    {
      method: 'POST',
      headers: { ...getAuthorizationHeaders() },
      signal: handlers.signal,
    },
  )
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
