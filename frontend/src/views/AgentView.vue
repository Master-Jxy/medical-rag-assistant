<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  downloadAgentArtifact,
  getAgentRun,
  listAgentRuns,
} from '../api/agent.js'
import { getApiErrorMessage } from '../api/http.js'
import { getDocumentTrace, openDocumentPreview } from '../api/citations.js'
import AgentComposer from '../features/agent-chat/AgentComposer.vue'
import AgentContextDrawer from '../features/agent-chat/AgentContextDrawer.vue'
import AgentConversation from '../features/agent-chat/AgentConversation.vue'
import AgentThreadSidebar from '../features/agent-chat/AgentThreadSidebar.vue'
import { useAgentStream } from '../features/agent-chat/useAgentStream.js'
import { useAgentThread } from '../features/agent-chat/useAgentThread.js'

const threadState = useAgentThread()
const optimisticMessages = ref([])
const errorMessage = ref('')
const notice = ref('')
const legacyRuns = ref([])
const legacySelected = ref(null)
const selectedSource = ref(null)
const threadDrawerOpen = ref(false)
const contextDrawerOpen = ref(false)
const downloadingId = ref('')
const references = ref({ messageIds: [], sourceIds: [], artifactIds: [] })

const referenceLabels = computed(() => [
  ...references.value.messageIds.map((id) => ({
    key: `message:${id}`,
    type: 'message',
    id,
    label: threadState.messages.value.find((item) => item.id === id)?.content?.slice(0, 18)
      || '历史消息',
  })),
  ...references.value.sourceIds.map((id) => ({
    key: `source:${id}`,
    type: 'source',
    id,
    label: sources.value.find((item) => item.document_id === id)?.file_name || `来源 ${id.slice(0, 8)}`,
  })),
  ...references.value.artifactIds.map((id) => ({
    key: `artifact:${id}`,
    type: 'artifact',
    id,
    label: artifacts.value.find((item) => item.id === id)?.file_name || '已有产物',
  })),
])

const stream = useAgentStream(async () => {
  optimisticMessages.value = []
  await threadState.reloadCurrent()
})

const displayMessages = computed(() => {
  if (legacySelected.value) {
    return [{
      id: `legacy-${legacySelected.value.id}`,
      role: 'assistant',
      status: legacySelected.value.status,
      content: legacySelected.value.final_result || legacySelected.value.task,
      run_id: legacySelected.value.id,
      metadata: {
        source_ids: [],
        artifact_ids: (legacySelected.value.artifacts || []).map((item) => item.id),
      },
    }]
  }
  const rows = [...threadState.messages.value, ...optimisticMessages.value]
  if (
    stream.state.value.assistantMessageId
    && !rows.some((item) => item.id === stream.state.value.assistantMessageId)
  ) {
    rows.push({
      id: stream.state.value.assistantMessageId,
      role: 'assistant',
      status: stream.state.value.phase,
      content: stream.state.value.output,
      run_id: stream.state.value.runId,
      metadata: {
        source_ids: stream.state.value.sources.map((item) => item.document_id).filter(Boolean),
        artifact_ids: stream.state.value.artifacts.map((item) => item.artifact_id).filter(Boolean),
      },
    })
  }
  return rows
})

const runDetails = computed(() => {
  if (!legacySelected.value) return threadState.runDetails.value
  return { [legacySelected.value.id]: legacySelected.value }
})

const sources = computed(() => {
  const rows = displayMessages.value.flatMap((item) => {
    if (item.metadata?.sources?.length) return item.metadata.sources
    return (item.metadata?.source_ids || []).map((document_id) => ({ document_id }))
  })
  rows.push(...stream.state.value.sources)
  return rows.filter(
    (item, index, all) => item.document_id
      && all.findIndex((other) => (
        other.document_id === item.document_id
        && other.chunk_id === item.chunk_id
        && other.page === item.page
      )) === index,
  )
})

const artifacts = computed(() => {
  const stored = Object.values(runDetails.value).flatMap((run) => run?.artifacts || [])
  const live = stream.state.value.artifacts.map((item) => ({
    id: item.artifact_id,
    file_name: item.file_name,
    mime_type: item.mime_type,
  }))
  return [...stored, ...live].filter(
    (item, index, rows) => rows.findIndex((other) => other.id === item.id) === index,
  )
})

async function selectThread(thread) {
  errorMessage.value = ''
  legacySelected.value = null
  try {
    await threadState.selectThread(thread)
    references.value = { messageIds: [], sourceIds: [], artifactIds: [] }
    threadDrawerOpen.value = false
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  }
}

async function createThread() {
  errorMessage.value = ''
  try {
    await threadState.newThread()
    legacySelected.value = null
    threadDrawerOpen.value = false
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  }
}

async function renameThread(thread) {
  const title = window.prompt('输入新的会话名称', thread.title)?.trim()
  if (!title) return
  try {
    await threadState.renameThread(thread, title)
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  }
}

async function archiveThread(thread) {
  try {
    await threadState.archiveThread(thread)
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  }
}

async function restoreThread(thread) {
  try {
    await threadState.restoreThread(thread)
    notice.value = '会话已恢复到进行中。'
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  }
}

async function showThreadStatus(status) {
  errorMessage.value = ''
  try {
    await threadState.showStatus(status)
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  }
}

async function removeThread(thread) {
  if (!window.confirm(`删除“${thread.title}”及其消息、运行和产物？`)) return
  try {
    await threadState.removeThread(thread)
    notice.value = '会话已删除。'
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  }
}

async function send(content) {
  errorMessage.value = ''
  notice.value = ''
  legacySelected.value = null
  try {
    let thread = threadState.currentThread.value
    if (!thread) thread = await threadState.newThread()
    if (thread.title === '新对话') {
      await threadState.renameThread(thread, content.slice(0, 30))
    }
    optimisticMessages.value = [{
      id: `pending-${Date.now()}`,
      role: 'user',
      status: 'pending',
      content,
      run_id: null,
      metadata: {},
    }]
    await stream.send(thread.id, content, references.value)
    references.value = { messageIds: [], sourceIds: [], artifactIds: [] }
  } catch (error) {
    optimisticMessages.value = []
    errorMessage.value = getApiErrorMessage(error)
  }
}

function toggleReference(type, item) {
  const field = `${type}Ids`
  const id = type === 'message'
    ? item.id
    : type === 'source'
      ? item.document_id
      : item.id
  const values = references.value[field]
  references.value = {
    ...references.value,
    [field]: values.includes(id)
      ? values.filter((value) => value !== id)
      : [...values, id],
  }
}

function removeReference(item) {
  toggleReference(item.type, item.type === 'source' ? { document_id: item.id } : item)
}

async function retry(messageId) {
  errorMessage.value = ''
  try {
    await stream.retry(messageId)
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  }
}

async function stop() {
  try {
    await stream.stop()
    notice.value = '正在安全停止当前任务。'
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  }
}

async function selectLegacy(run) {
  try {
    legacySelected.value = await getAgentRun(run.id)
    threadState.currentThread.value = null
    threadState.messages.value = []
    threadDrawerOpen.value = false
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  }
}

async function selectSource(source, open = false) {
  const documentId = typeof source === 'string' ? source : source.document_id
  const page = typeof source === 'string' ? null : source.page
  try {
    selectedSource.value = await getDocumentTrace(documentId)
    contextDrawerOpen.value = true
    if (open) await openDocumentPreview(documentId, page)
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  }
}

async function download(artifact) {
  downloadingId.value = artifact.id
  try {
    const blob = await downloadAgentArtifact(artifact.id)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = artifact.file_name
    anchor.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    downloadingId.value = ''
  }
}

onMounted(async () => {
  try {
    const [runs] = await Promise.all([
      listAgentRuns(100),
      threadState.loadThreads(true),
    ])
    legacyRuns.value = runs.items.filter((item) => !item.thread_id)
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  }
})
</script>

<template>
  <section class="agent-page">
    <header class="page-toolbar">
      <div>
        <span>AGENT CHAT V3</span>
        <h1>资料整理 Agent</h1>
        <p>连续会话承载任务上下文；公开展示计划、工具、来源与产物，不展示隐藏推理。</p>
      </div>
      <div class="mobile-tools">
        <button aria-label="打开Agent会话列表" @click="threadDrawerOpen = true">会话</button>
        <button aria-label="打开来源与产物" @click="contextDrawerOpen = true">上下文</button>
      </div>
    </header>

    <div v-if="errorMessage || stream.state.value.error" class="state-panel error">
      {{ errorMessage || stream.state.value.error }}
    </div>
    <div v-if="notice" class="state-panel success">{{ notice }}</div>

    <div class="agent-workspace">
      <div class="drawer-shell threads" :class="{ open: threadDrawerOpen }">
        <button class="drawer-close" aria-label="关闭Agent会话列表" @click="threadDrawerOpen = false">×</button>
        <AgentThreadSidebar
          :threads="threadState.threads.value"
          :selected-id="threadState.currentThread.value?.id || ''"
          :legacy-runs="legacyRuns"
          :loading="threadState.loading.value"
          :status-filter="threadState.statusFilter.value"
          @new="createThread"
          @select="selectThread"
          @rename="renameThread"
          @archive="archiveThread"
          @restore="restoreThread"
          @delete="removeThread"
          @legacy="selectLegacy"
          @show-active="showThreadStatus('active')"
          @show-archived="showThreadStatus('archived')"
        />
      </div>

      <main class="conversation-shell">
        <div class="conversation-title">
          <strong>{{ legacySelected?.task || threadState.currentThread.value?.title || '新Agent会话' }}</strong>
          <span v-if="stream.running.value">运行中</span>
        </div>
        <AgentConversation
          :messages="displayMessages"
          :run-details="runDetails"
          :live="stream.state.value"
          @retry="retry"
          @select-source="selectSource"
          @select-artifact="contextDrawerOpen = true"
          @toggle-reference="toggleReference('message', $event)"
        />
        <AgentComposer
          :disabled="stream.running.value"
          :running="stream.running.value"
          :references="referenceLabels"
          @send="send"
          @stop="stop"
          @remove-reference="removeReference"
        />
      </main>

      <div class="drawer-shell context" :class="{ open: contextDrawerOpen }">
        <button class="drawer-close" aria-label="关闭来源与产物" @click="contextDrawerOpen = false">×</button>
        <AgentContextDrawer
          :sources="sources"
          :artifacts="artifacts"
          :selected-source="selectedSource"
          :referenced-source-ids="references.sourceIds"
          :referenced-artifact-ids="references.artifactIds"
          @open-source="selectSource($event, true)"
          @download="download"
          @toggle-source-reference="toggleReference('source', $event)"
          @toggle-artifact-reference="toggleReference('artifact', $event)"
        />
      </div>
    </div>
  </section>
</template>

<style scoped>
.agent-page { min-width: 0; }
.page-toolbar { display: flex; justify-content: space-between; gap: 16px; }
.agent-workspace { height: min(720px, calc(100vh - 190px)); min-height: 560px; display: grid; grid-template-columns: minmax(220px, 270px) minmax(0, 1fr) minmax(220px, 280px); gap: 12px; }
.drawer-shell { min-width: 0; min-height: 0; }
.drawer-close, .mobile-tools { display: none; }
.conversation-shell { position: relative; min-width: 0; min-height: 0; overflow: hidden; background: #f6f8f7; border: 1px solid var(--border); border-radius: 8px; }
.conversation-title { height: 48px; padding: 0 18px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); background: #fff; }
.conversation-title span { color: #276749; font-size: 12px; }
.conversation-shell :deep(.conversation) { height: calc(100% - 48px); box-sizing: border-box; }
@media (max-width: 1000px) {
  .mobile-tools { display: flex; gap: 8px; }
  .mobile-tools button { padding: 7px 10px; border: 1px solid var(--border); border-radius: 5px; background: #fff; }
  .agent-workspace { grid-template-columns: minmax(0, 1fr); }
  .drawer-shell { display: none; position: fixed; z-index: 30; top: 72px; bottom: 12px; width: min(330px, calc(100vw - 24px)); }
  .drawer-shell.open { display: block; }
  .drawer-shell.threads { left: 12px; }
  .drawer-shell.context { right: 12px; }
  .drawer-close { display: block; position: absolute; z-index: 2; top: 8px; right: 10px; border: 0; background: transparent; font-size: 22px; cursor: pointer; }
  .drawer-shell :deep(aside) { box-shadow: 0 16px 40px rgb(20 40 31 / 22%); }
}
@media (max-width: 480px) {
  .agent-workspace { height: calc(100vh - 160px); min-height: 520px; }
  .page-toolbar p { display: none; }
}
</style>
