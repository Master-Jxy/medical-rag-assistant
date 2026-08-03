import { reactive } from 'vue'

const registryEntries = new Map()

const LOCAL_RUNNING_PHASES = new Set([
  'pending',
  'creating_message',
  'planning',
  'running_tools',
  'streaming_answer',
  'running',
  'stopping',
  'settling',
])
const SERVER_RUNNING_PHASES = new Set(['pending', 'running', 'stopping'])

export function useConversationStreamRegistry(scope = 'default') {
  if (!registryEntries.has(scope)) registryEntries.set(scope, reactive(new Map()))
  const entries = registryEntries.get(scope)

  function get(id) {
    return id ? entries.get(id) || null : null
  }

  function start(id, values = {}) {
    const current = get(id)
    if (current && LOCAL_RUNNING_PHASES.has(current.phase)) {
      throw new Error('当前会话正在生成，请等待完成后再试。')
    }
    const entry = {
      phase: 'pending',
      requestId: '',
      runId: '',
      controller: new AbortController(),
      localUnread: false,
      error: '',
      startedAt: Date.now(),
      seenEventIds: new Set(),
      ...values,
    }
    entries.set(id, entry)
    return entry
  }

  function patch(id, values) {
    const entry = get(id)
    if (!entry) return null
    Object.assign(entry, values)
    return entry
  }

  function isRunning(id, serverStatus = 'idle') {
    const entry = get(id)
    if (entry) return LOCAL_RUNNING_PHASES.has(entry.phase)
    return SERVER_RUNNING_PHASES.has(serverStatus)
  }

  function markUnread(id) {
    const entry = get(id)
    if (entry) entry.localUnread = true
  }

  function clearUnread(id) {
    const entry = get(id)
    if (entry) entry.localUnread = false
  }

  function hasUnread(id, serverUnread = false) {
    return Boolean(get(id)?.localUnread || serverUnread)
  }

  function acceptEvent(id, data = {}) {
    const eventId = data.event_id || data.eventId
    if (!eventId) return true
    const entry = get(id)
    if (!entry || entry.seenEventIds.has(eventId)) return false
    entry.seenEventIds.add(eventId)
    return true
  }

  function finish(id, phase = 'completed') {
    return patch(id, { phase, controller: null })
  }

  function abort(id) {
    const entry = get(id)
    entry?.controller?.abort()
  }

  function remove(id) {
    abort(id)
    entries.delete(id)
  }

  function abortAll() {
    for (const entry of entries.values()) entry.controller?.abort()
    entries.clear()
  }

  return {
    entries,
    get,
    start,
    patch,
    finish,
    isRunning,
    markUnread,
    clearUnread,
    hasUnread,
    acceptEvent,
    abort,
    remove,
    abortAll,
  }
}

export function abortAllConversationStreams() {
  for (const entries of registryEntries.values()) {
    for (const entry of entries.values()) entry.controller?.abort()
    entries.clear()
  }
}
