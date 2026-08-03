import { computed, reactive, ref } from 'vue'
import {
  createAgentThread,
  deleteAgentThread,
  getAgentRun,
  listAgentMessages,
  listAgentThreads,
  markAgentThreadRead,
  updateAgentThread,
} from '../../api/agent.js'

const TERMINAL_MESSAGE_STATUSES = new Set(['completed', 'failed', 'stopped'])

function maxReadableSequence(rows) {
  return rows.reduce((maximum, row) => (
    TERMINAL_MESSAGE_STATUSES.has(row.status)
      ? Math.max(maximum, Number(row.sequence_no || 0))
      : maximum
  ), 0)
}

export function useAgentThread() {
  const threads = ref([])
  const currentThread = ref(null)
  const messageCache = reactive(new Map())
  const runDetailsCache = reactive(new Map())
  const loading = ref(false)
  const statusFilter = ref('active')
  let selectionVersion = 0

  const messages = computed(() => (
    messageCache.get(currentThread.value?.id) || []
  ))
  const runDetails = computed(() => (
    runDetailsCache.get(currentThread.value?.id) || {}
  ))

  function findThread(threadId) {
    return threads.value.find((item) => item.id === threadId) || null
  }

  function updateThreadSummary(threadId, changes) {
    const thread = findThread(threadId)
    if (thread) Object.assign(thread, changes)
    if (currentThread.value?.id === threadId) Object.assign(currentThread.value, changes)
  }

  function clearCurrent() {
    selectionVersion += 1
    currentThread.value = null
  }

  async function loadThreadData(thread) {
    const result = await listAgentMessages(thread.id)
    const rows = result.items
    const runIds = [...new Set(rows.map((item) => item.run_id).filter(Boolean))]
    const runs = await Promise.all(runIds.map(async (runId) => [runId, await getAgentRun(runId)]))
    const details = {}
    for (const [runId, run] of runs) {
      details[runId] = run
      if (run.trigger_message_id) details[run.trigger_message_id] = run
    }
    messageCache.set(thread.id, rows)
    runDetailsCache.set(thread.id, details)
    return { rows, details }
  }

  async function markRead(threadId, rows) {
    const sequence = maxReadableSequence(rows)
    if (!sequence) return
    const result = await markAgentThreadRead(threadId, sequence)
    updateThreadSummary(threadId, {
      last_read_sequence: result.last_read_sequence,
      has_unread: false,
    })
  }

  async function loadThreads(selectFirst = true) {
    loading.value = true
    try {
      const incoming = (await listAgentThreads(statusFilter.value)).items
      threads.value = incoming.map((item) => ({ ...item }))
      if (currentThread.value) {
        const refreshed = findThread(currentThread.value.id)
        if (refreshed) currentThread.value = refreshed
      }
      if (selectFirst && !currentThread.value && threads.value.length) {
        await selectThread(threads.value[0])
      }
    } finally {
      loading.value = false
    }
  }

  async function newThread(title = '新对话', assistantMode = 'general') {
    const thread = await createAgentThread(title, assistantMode)
    statusFilter.value = 'active'
    threads.value = [thread, ...threads.value.filter((item) => (
      item.id !== thread.id && item.status === 'active'
    ))]
    messageCache.set(thread.id, [])
    runDetailsCache.set(thread.id, {})
    await selectThread(thread)
    return thread
  }

  async function selectThread(thread) {
    const version = ++selectionVersion
    currentThread.value = thread
    const { rows } = await loadThreadData(thread)
    if (version !== selectionVersion || currentThread.value?.id !== thread.id) return
    await markRead(thread.id, rows)
  }

  async function reloadThread(threadId, { markAsRead = false } = {}) {
    const thread = findThread(threadId) || (currentThread.value?.id === threadId
      ? currentThread.value
      : null)
    if (!thread) return null
    const result = await loadThreadData(thread)
    if (markAsRead) await markRead(threadId, result.rows)
    return result
  }

  async function renameThread(thread, title) {
    const updated = await updateAgentThread(thread.id, { title })
    Object.assign(thread, updated)
    if (currentThread.value?.id === updated.id) currentThread.value = thread
  }

  async function setAssistantMode(thread, assistantMode) {
    const updated = await updateAgentThread(thread.id, { assistant_mode: assistantMode })
    Object.assign(thread, updated)
    if (currentThread.value?.id === updated.id) currentThread.value = thread
    return updated
  }

  async function archiveThread(thread) {
    await updateAgentThread(thread.id, { status: 'archived' })
    threads.value = threads.value.filter((item) => item.id !== thread.id)
    if (currentThread.value?.id === thread.id) {
      clearCurrent()
      if (threads.value.length) await selectThread(threads.value[0])
    }
  }

  async function restoreThread(thread) {
    await updateAgentThread(thread.id, { status: 'active' })
    threads.value = threads.value.filter((item) => item.id !== thread.id)
    if (currentThread.value?.id === thread.id) {
      clearCurrent()
      if (threads.value.length) await selectThread(threads.value[0])
    }
  }

  async function showStatus(status) {
    if (statusFilter.value === status) return
    statusFilter.value = status
    clearCurrent()
    await loadThreads(true)
  }

  async function removeThread(thread) {
    await deleteAgentThread(thread.id)
    threads.value = threads.value.filter((item) => item.id !== thread.id)
    messageCache.delete(thread.id)
    runDetailsCache.delete(thread.id)
    if (currentThread.value?.id === thread.id) {
      clearCurrent()
      if (threads.value.length) await selectThread(threads.value[0])
    }
  }

  return {
    threads,
    currentThread,
    messages,
    runDetails,
    messageCache,
    runDetailsCache,
    loading,
    statusFilter,
    findThread,
    updateThreadSummary,
    loadThreads,
    newThread,
    selectThread,
    reloadThread,
    renameThread,
    setAssistantMode,
    archiveThread,
    restoreThread,
    showStatus,
    removeThread,
    clearCurrent,
  }
}
