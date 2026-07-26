import { ref } from 'vue'
import {
  createAgentThread,
  deleteAgentThread,
  getAgentRun,
  listAgentMessages,
  listAgentThreads,
  updateAgentThread,
} from '../../api/agent.js'

export function useAgentThread() {
  const threads = ref([])
  const currentThread = ref(null)
  const messages = ref([])
  const runDetails = ref({})
  const loading = ref(false)

  async function loadThreads(selectFirst = true) {
    loading.value = true
    try {
      threads.value = (await listAgentThreads('active')).items
      if (selectFirst && !currentThread.value && threads.value.length) {
        await selectThread(threads.value[0])
      }
    } finally {
      loading.value = false
    }
  }

  async function newThread(title = '新对话') {
    const thread = await createAgentThread(title)
    threads.value = [thread, ...threads.value]
    await selectThread(thread)
    return thread
  }

  async function selectThread(thread) {
    currentThread.value = thread
    const result = await listAgentMessages(thread.id)
    messages.value = result.items
    const runs = await Promise.all(
      messages.value
        .filter((item) => item.run_id)
        .map(async (item) => [item.run_id, await getAgentRun(item.run_id)]),
    )
    const details = {}
    for (const [runId, run] of runs) {
      details[runId] = run
      if (run.trigger_message_id) details[run.trigger_message_id] = run
    }
    runDetails.value = details
  }

  async function renameThread(thread, title) {
    const updated = await updateAgentThread(thread.id, { title })
    Object.assign(thread, updated)
    if (currentThread.value?.id === updated.id) currentThread.value = thread
  }

  async function archiveThread(thread) {
    await updateAgentThread(thread.id, { status: 'archived' })
    threads.value = threads.value.filter((item) => item.id !== thread.id)
    if (currentThread.value?.id === thread.id) {
      currentThread.value = null
      messages.value = []
      if (threads.value.length) await selectThread(threads.value[0])
    }
  }

  async function removeThread(thread) {
    await deleteAgentThread(thread.id)
    threads.value = threads.value.filter((item) => item.id !== thread.id)
    if (currentThread.value?.id === thread.id) {
      currentThread.value = null
      messages.value = []
      if (threads.value.length) await selectThread(threads.value[0])
    }
  }

  async function reloadCurrent() {
    if (currentThread.value) await selectThread(currentThread.value)
    await loadThreads(false)
  }

  return {
    threads,
    currentThread,
    messages,
    runDetails,
    loading,
    loadThreads,
    newThread,
    selectThread,
    renameThread,
    archiveThread,
    removeThread,
    reloadCurrent,
  }
}
