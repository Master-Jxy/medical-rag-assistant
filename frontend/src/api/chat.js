import http, { apiBaseUrl, createApiErrorFromResponse } from './http.js'

export async function askKnowledgeBase(question, topK = 4) {
  const response = await http.post('/chat', {
    question,
    top_k: topK,
  })
  return response.data
}

function createUserError(message) {
  const error = new Error(message)
  error.userMessage = message
  return error
}

function parseSseFrame(frame) {
  let eventName = 'message'
  const dataLines = []

  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith('event:')) eventName = line.slice(6).trim()
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
  }

  if (!dataLines.length) return null
  return { event: eventName, data: JSON.parse(dataLines.join('\n')) }
}

function handleSseEvent(item, handlers) {
  if (!item) return
  if (item.event === 'token') handlers.onToken?.(item.data.content || '')
  if (item.event === 'sources') handlers.onSources?.(item.data.sources || [])
  if (item.event === 'done') handlers.onDone?.(item.data)
  if (item.event === 'stopped') handlers.onStopped?.(item.data)
  if (item.event === 'error') throw createUserError(item.data.message || '流式回答失败。')
}

export async function consumeSseResponse(response, handlers = {}) {
  if (!response.body) throw createUserError('浏览器不支持读取流式响应。')

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  const cancelReader = () => {
    // AbortController 只保证前端 fetch 停止；显式取消读取器才能尽快通知后端关闭 SSE。
    reader.cancel().catch(() => {})
  }
  handlers.signal?.addEventListener('abort', cancelReader, { once: true })

  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done })

      const frames = buffer.split(/\r?\n\r?\n/)
      buffer = frames.pop() || ''
      for (const frame of frames) handleSseEvent(parseSseFrame(frame), handlers)

      if (done) break
    }

    if (buffer.trim()) handleSseEvent(parseSseFrame(buffer), handlers)
  } finally {
    handlers.signal?.removeEventListener('abort', cancelReader)
  }

  if (handlers.signal?.aborted) {
    const error = new Error('已停止生成。')
    error.name = 'AbortError'
    throw error
  }
}

export async function streamKnowledgeBase(question, options = {}) {
  const response = await fetch(`${apiBaseUrl}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, top_k: options.topK || 4 }),
    signal: options.signal,
  })

  if (!response.ok) {
    throw await createApiErrorFromResponse(response)
  }

  await consumeSseResponse(response, options)
}
