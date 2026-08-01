<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { Bot, PanelLeft, X } from '@lucide/vue'
import { downloadAgentArtifact } from '../api/agent.js'
import { getApiErrorMessage } from '../api/http.js'
import { getDocumentTrace, openDocumentPreview } from '../api/citations.js'
import AgentComposer from '../features/agent-chat/AgentComposer.vue'
import AgentContextDrawer from '../features/agent-chat/AgentContextDrawer.vue'
import AgentConversation from '../features/agent-chat/AgentConversation.vue'
import AgentThreadSidebar from '../features/agent-chat/AgentThreadSidebar.vue'
import { useAgentStream } from '../features/agent-chat/useAgentStream.js'
import { useAgentThread } from '../features/agent-chat/useAgentThread.js'
import { useAgentTimeline } from '../features/agent-chat/useAgentTimeline.js'

const threadState = useAgentThread()
const timeline = useAgentTimeline()
const errorMessage = ref('')
const notice = ref('')
const selectedSource = ref(null)
const selectedArtifact = ref(null)
const threadDrawerOpen = ref(false)
const contextDrawerOpen = ref(false)
const downloadingId = ref('')
const composer = ref(null)
const references = ref({ messageIds: [], sourceIds: [], artifactIds: [] })
const renameTarget = ref(null)
const renameTitle = ref('')
const deleteTarget = ref(null)
const threadActionPending = ref(false)

async function focusComposer() {
  await nextTick()
  composer.value?.focus()
}

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
  await threadState.reloadCurrent()
  timeline.hydrate(threadState.messages.value, threadState.runDetails.value)
  await focusComposer()
}, timeline.handle)

const displayMessages = timeline.messages
const runDetails = computed(() => threadState.runDetails.value)

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
  try {
    await threadState.selectThread(thread)
    timeline.hydrate(threadState.messages.value, threadState.runDetails.value)
    references.value = { messageIds: [], sourceIds: [], artifactIds: [] }
    threadDrawerOpen.value = false
    await focusComposer()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  }
}

async function createThread() {
  errorMessage.value = ''
  try {
    await threadState.newThread()
    timeline.hydrate(threadState.messages.value, threadState.runDetails.value)
    threadDrawerOpen.value = false
    await focusComposer()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  }
}

async function renameThread(thread) {
  renameTarget.value = thread
  renameTitle.value = thread.title
}

async function confirmRename() {
  const title = renameTitle.value.trim()
  if (!renameTarget.value || !title || threadActionPending.value) return
  threadActionPending.value = true
  try {
    await threadState.renameThread(renameTarget.value, title)
    renameTarget.value = null
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    threadActionPending.value = false
  }
}

async function archiveThread(thread) {
  try {
    await threadState.archiveThread(thread)
    timeline.hydrate(threadState.messages.value, threadState.runDetails.value)
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  }
}

async function restoreThread(thread) {
  try {
    await threadState.restoreThread(thread)
    timeline.hydrate(threadState.messages.value, threadState.runDetails.value)
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
  deleteTarget.value = thread
}

async function confirmRemoveThread() {
  if (!deleteTarget.value || threadActionPending.value) return
  threadActionPending.value = true
  try {
    await threadState.removeThread(deleteTarget.value)
    timeline.hydrate(threadState.messages.value, threadState.runDetails.value)
    references.value = { messageIds: [], sourceIds: [], artifactIds: [] }
    selectedSource.value = null
    selectedArtifact.value = null
    contextDrawerOpen.value = false
    deleteTarget.value = null
    notice.value = '会话已删除。'
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    threadActionPending.value = false
  }
}

async function send(content) {
  errorMessage.value = ''
  notice.value = ''
  try {
    let thread = threadState.currentThread.value
    if (!thread) thread = await threadState.newThread()
    if (thread.title === '新对话') {
      await threadState.renameThread(thread, content.slice(0, 30))
    }
    timeline.beginUser(content)
    await stream.send(thread.id, content, references.value)
    references.value = { messageIds: [], sourceIds: [], artifactIds: [] }
  } catch (error) {
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

async function selectSource(source, open = false) {
  const documentId = typeof source === 'string' ? source : source.document_id
  const page = typeof source === 'string' ? null : source.page
  try {
    selectedArtifact.value = null
    selectedSource.value = await getDocumentTrace(documentId)
    contextDrawerOpen.value = true
    if (open) await openDocumentPreview(documentId, page)
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  }
}

function selectArtifact(artifact) {
  selectedSource.value = null
  selectedArtifact.value = artifact
  contextDrawerOpen.value = true
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
    await threadState.loadThreads(true)
    timeline.hydrate(threadState.messages.value, threadState.runDetails.value)
    await focusComposer()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  }
})
</script>

<template>
  <section class="agent-page">
    <header class="page-toolbar">
      <div>
        <span>AGENT CHAT V3.2</span>
        <h1>Agent 工作台</h1>
        <p>通过受控工具完成资料检索、比较、摘要和学习报告任务。</p>
      </div>
      <div class="mobile-tools">
        <button aria-label="打开Agent会话列表" @click="threadDrawerOpen = true"><PanelLeft :size="17" />会话</button>
      </div>
    </header>

    <div v-if="errorMessage || stream.state.value.error" class="state-panel error">
      {{ errorMessage || stream.state.value.error }}
    </div>
    <div v-if="notice" class="state-panel success">{{ notice }}</div>

    <div class="agent-workspace">
      <button v-if="threadDrawerOpen" class="thread-backdrop" aria-label="关闭Agent会话列表" @click="threadDrawerOpen = false" />
      <div class="drawer-shell threads" :class="{ open: threadDrawerOpen }">
        <button class="drawer-close" aria-label="关闭Agent会话列表" @click="threadDrawerOpen = false"><X :size="18" /></button>
        <AgentThreadSidebar
          :threads="threadState.threads.value"
          :selected-id="threadState.currentThread.value?.id || ''"
          :loading="threadState.loading.value"
          :status-filter="threadState.statusFilter.value"
          @new="createThread"
          @select="selectThread"
          @rename="renameThread"
          @archive="archiveThread"
          @restore="restoreThread"
          @delete="removeThread"
          @show-active="showThreadStatus('active')"
          @show-archived="showThreadStatus('archived')"
        />
      </div>

      <main class="conversation-shell">
        <div class="conversation-title">
          <strong><Bot :size="16" />{{ threadState.currentThread.value?.title || '新Agent会话' }}</strong>
          <span v-if="stream.running.value"><i></i> Agent 正在工作</span>
        </div>
        <AgentConversation
          :messages="displayMessages"
          :run-details="runDetails"
          :live="stream.state.value"
          @retry="retry"
          @select-source="selectSource"
          @select-artifact="selectArtifact"
          @toggle-reference="toggleReference('message', $event)"
          @toggle-source-reference="toggleReference('source', $event)"
          @toggle-artifact-reference="toggleReference('artifact', $event)"
        />
        <AgentComposer
          ref="composer"
          :disabled="stream.running.value"
          :running="stream.running.value"
          :references="referenceLabels"
          @send="send"
          @stop="stop"
          @remove-reference="removeReference"
        />
      </main>

      <div v-if="contextDrawerOpen" class="detail-overlay" @click.self="contextDrawerOpen = false">
        <div class="drawer-shell context open">
        <button class="drawer-close" aria-label="关闭来源与产物" @click="contextDrawerOpen = false"><X :size="18" /></button>
        <AgentContextDrawer
          :sources="selectedSource ? [selectedSource] : []"
          :artifacts="selectedArtifact ? [selectedArtifact] : []"
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
    </div>

    <div v-if="renameTarget" class="thread-dialog-backdrop" @click.self="!threadActionPending && (renameTarget = null)">
      <form class="thread-dialog" role="dialog" aria-modal="true" aria-labelledby="rename-thread-title" @submit.prevent="confirmRename">
        <header><div><span>会话设置</span><h2 id="rename-thread-title">重命名会话</h2></div><button type="button" aria-label="关闭" @click="renameTarget = null"><X :size="18" /></button></header>
        <label>会话名称<input v-model="renameTitle" maxlength="80" autofocus /></label>
        <footer><el-button :disabled="threadActionPending" @click="renameTarget = null">取消</el-button><el-button type="primary" native-type="submit" :loading="threadActionPending" :disabled="!renameTitle.trim()">保存</el-button></footer>
      </form>
    </div>

    <div v-if="deleteTarget" class="thread-dialog-backdrop" @click.self="!threadActionPending && (deleteTarget = null)">
      <div class="thread-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-thread-title">
        <header><div><span>危险操作</span><h2 id="delete-thread-title">删除会话</h2></div><button type="button" aria-label="关闭" @click="deleteTarget = null"><X :size="18" /></button></header>
        <p>“{{ deleteTarget.title }}”中的消息、运行记录与产物索引都会删除，此操作无法撤销。</p>
        <footer><el-button :disabled="threadActionPending" @click="deleteTarget = null">取消</el-button><el-button type="danger" :loading="threadActionPending" @click="confirmRemoveThread">确认删除</el-button></footer>
      </div>
    </div>
  </section>
</template>

<style scoped>
.agent-page { min-width: 0; min-height: calc(100vh - 92px); display: flex; flex-direction: column; }
.page-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 14px;
}
.page-toolbar span {
  color: var(--primary);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0;
}
.page-toolbar h1 { margin: 3px 0 4px; font-size: 22px; line-height: 30px; }
.page-toolbar p { margin: 0; color: var(--muted); font-size: 13px; }
.agent-workspace {
  min-height: 560px;
  flex: 1;
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 12px;
}
.drawer-shell { min-width: 0; min-height: 0; }
.drawer-close, .mobile-tools { display: none; }
.conversation-shell {
  position: relative;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}
.conversation-title {
  height: 48px;
  padding: 0 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--line);
  background: rgba(255, 255, 255, .96);
}
.conversation-title strong { min-width: 0; display: flex; align-items: center; gap: 7px; overflow: hidden; color: var(--ink); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.conversation-title span {
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--primary);
  font-size: 12px;
}
.conversation-title i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #18a875;
  box-shadow: 0 0 0 5px rgba(24, 168, 117, .1);
}
.conversation-shell :deep(.conversation) { height: calc(100% - 48px); box-sizing: border-box; }
.detail-overlay { position: fixed; z-index: 40; inset: 0; display: grid; place-items: center; padding: 24px; background: rgb(15 30 24 / 36%); }
.detail-overlay .context { display: block; position: relative; width: min(560px, 100%); max-height: min(680px, calc(100vh - 48px)); }
.detail-overlay .context :deep(aside) { max-height: inherit; box-shadow: 0 18px 50px rgb(20 40 31 / 24%); }
.thread-dialog-backdrop { position: fixed; inset: 0; z-index: 70; display: grid; place-items: center; padding: 20px; background: rgba(18,39,34,.5); }
.thread-dialog { width: min(460px, 100%); display: grid; gap: 16px; padding: 22px; border-radius: 8px; background: #fff; box-shadow: 0 24px 70px rgba(0,0,0,.22); }
.thread-dialog header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.thread-dialog header span { color: var(--brand); font-size: 10px; font-weight: 700; }
.thread-dialog h2 { margin: 3px 0 0; color: var(--ink); font-size: 18px; }
.thread-dialog header button { width: 32px; height: 32px; display: grid; place-items: center; border: 0; border-radius: 5px; color: var(--muted); background: transparent; cursor: pointer; }
.thread-dialog label { display: grid; gap: 6px; color: var(--ink); font-size: 12px; font-weight: 600; }
.thread-dialog input { width: 100%; padding: 10px; border: 1px solid var(--line); border-radius: 6px; outline: 0; }
.thread-dialog input:focus { border-color: var(--action); box-shadow: 0 0 0 3px #e7efff; }
.thread-dialog p { margin: 0; color: var(--muted); font-size: 13px; line-height: 1.7; }
.thread-dialog footer { display: flex; justify-content: flex-end; gap: 8px; }
.thread-backdrop { display: none; }
@media (max-width: 1000px) {
  .mobile-tools { display: flex; gap: 8px; }
  .mobile-tools button { display: inline-flex; align-items: center; gap: 6px; padding: 7px 10px; border: 1px solid var(--border); border-radius: 6px; background: #fff; }
  .agent-workspace { grid-template-columns: minmax(0, 1fr); }
  .drawer-shell { display: none; position: fixed; z-index: 72; top: 0; bottom: 0; width: min(310px, calc(100vw - 44px)); }
  .drawer-shell.open { display: block; }
  .drawer-shell.threads { left: 0; }
  .detail-overlay .drawer-shell.context { inset: auto; width: min(560px, 100%); }
  .drawer-close { width: 32px; height: 32px; display: grid; place-items: center; position: absolute; z-index: 2; top: 8px; right: 10px; border: 0; border-radius: 5px; color: var(--muted); background: transparent; cursor: pointer; }
  .drawer-shell :deep(aside) { box-shadow: 0 16px 40px rgb(20 40 31 / 22%); }
  .thread-backdrop { position: fixed; inset: 0; z-index: 70; display: block; border: 0; background: rgba(15,24,22,.5); }
}
@media (max-width: 480px) {
  .agent-page { min-height: 100vh; padding: 12px; }
  .agent-workspace { min-height: 520px; }
  .page-toolbar > div:first-child p, .page-toolbar > div:first-child > span { display: none; }
  .page-toolbar h1 { margin: 2px 0; font-size: 18px; }
}
</style>
