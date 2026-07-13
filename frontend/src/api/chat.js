import http, { apiBaseUrl } from './http.js'

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
  if (item.event === 'error') throw createUserError(item.data.message || '流式回答失败。')
}

export async function consumeSseResponse(response, handlers = {}) {
  if (!response.body) throw createUserError('浏览器不支持读取流式响应。')

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })

    const frames = buffer.split(/\r?\n\r?\n/)
    buffer = frames.pop() || ''
    for (const frame of frames) handleSseEvent(parseSseFrame(frame), handlers)

    if (done) break
  }

  if (buffer.trim()) handleSseEvent(parseSseFrame(buffer), handlers)
}

export async function streamKnowledgeBase(question, options = {}) {
  const response = await fetch(`${apiBaseUrl}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, top_k: options.topK || 4 }),
    signal: options.signal,
  })

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
