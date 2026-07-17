<script setup>
import { nextTick, onMounted, reactive, ref } from 'vue'

import {
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  stopConversationStream,
  streamConversation,
} from '../api/conversations.js'
import { getApiErrorMessage } from '../api/http.js'

const WELCOME_MESSAGE = {
  id: 'welcome',
  role: 'assistant',
  content: '你好，我会根据已上传的知识库资料回答问题，并展示引用来源。',
  sources: [],
}

const question = ref('')
const sending = ref(false)
const stopping = ref(false)
const loadingConversations = ref(true)
const loadingMessages = ref(false)
const errorMessage = ref('')
const conversations = ref([])
const activeConversationId = ref('')
const messages = ref([{ ...WELCOME_MESSAGE }])
const messageArea = ref(null)
const activeController = ref(null)
const activeIdempotencyKey = ref('')
const deleteTarget = ref(null)
const deleting = ref(false)

function mapStoredMessage(message) {
  let content = message.content
  if (message.role === 'assistant' && !content) {
    if (message.status === 'failed') content = '本次回答失败，请重新提问。'
    if (message.status === 'pending') content = '上次回答未正常结束，请重新提问。'
    if (message.status === 'stopped') content = '回答已停止。'
  }
  return {
    id: message.id,
    role: message.role,
    content,
    sources: message.sources || [],
    sourcesExpanded: false,
    requestId: message.request_id,
    status: message.status,
  }
}

async function scrollToBottom() {
  await nextTick()
  if (messageArea.value) messageArea.value.scrollTop = messageArea.value.scrollHeight
}

async function refreshConversationList() {
  const data = await listConversations()
  conversations.value = data.conversations
}

async function selectConversation(conversationId) {
  if (sending.value || conversationId === activeConversationId.value) return
  errorMessage.value = ''
  loadingMessages.value = true
  try {
    const conversation = await getConversation(conversationId)
    activeConversationId.value = conversation.id
    messages.value = conversation.messages.length
      ? conversation.messages.map(mapStoredMessage)
      : [{ ...WELCOME_MESSAGE }]
    await scrollToBottom()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    loadingMessages.value = false
  }
}

async function startNewConversation() {
  if (sending.value) return
  errorMessage.value = ''
  try {
    const conversation = await createConversation()
    conversations.value.unshift(conversation)
    activeConversationId.value = conversation.id
    messages.value = [{ ...WELCOME_MESSAGE }]
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  }
}

function requestDelete(conversation) {
  if (sending.value) return
  deleteTarget.value = conversation
  errorMessage.value = ''
}

async function confirmDelete() {
  if (!deleteTarget.value || deleting.value) return
  const target = deleteTarget.value
  const deletingActiveConversation = target.id === activeConversationId.value
  deleting.value = true
  errorMessage.value = ''

  try {
    await deleteConversation(target.id)
    conversations.value = conversations.value.filter((item) => item.id !== target.id)
    deleteTarget.value = null

    if (deletingActiveConversation) {
      activeConversationId.value = ''
      if (conversations.value.length) {
        await selectConversation(conversations.value[0].id)
      } else {
        messages.value = [{ ...WELCOME_MESSAGE }]
      }
    }
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    deleting.value = false
  }
}

async function ensureConversation() {
  if (activeConversationId.value) return activeConversationId.value
  const conversation = await createConversation()
  conversations.value.unshift(conversation)
  activeConversationId.value = conversation.id
  return conversation.id
}

async function sendQuestion() {
  const cleanedQuestion = question.value.trim()
  if (!cleanedQuestion || sending.value) return

  errorMessage.value = ''
  let conversationId
  try {
    conversationId = await ensureConversation()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
    return
  }

  if (messages.value.length === 1 && messages.value[0].id === 'welcome') messages.value = []
  const userMessage = reactive({
    id: crypto.randomUUID(),
    role: 'user',
    content: cleanedQuestion,
    sources: [],
  })
  const assistantMessage = reactive({
    id: crypto.randomUUID(),
    role: 'assistant',
    content: '',
    sources: [],
    streaming: true,
    sourcesExpanded: false,
  })
  messages.value.push(userMessage, assistantMessage)
  question.value = ''
  sending.value = true
  activeController.value = new AbortController()
  const idempotencyKey = crypto.randomUUID()
  activeIdempotencyKey.value = idempotencyKey
  await scrollToBottom()

  try {
    await streamConversation(conversationId, cleanedQuestion, {
      idempotencyKey,
      signal: activeController.value.signal,
      onToken(content) {
        assistantMessage.content += content
        scrollToBottom()
      },
      onSources(sources) {
        assistantMessage.sources = sources
      },
      onDone(data) {
        userMessage.id = data.user_message_id || userMessage.id
        assistantMessage.id = data.assistant_message_id || assistantMessage.id
        assistantMessage.requestId = data.request_id
        assistantMessage.disclaimer = data.disclaimer
      },
      onStopped(data) {
        userMessage.id = data.user_message_id || userMessage.id
        assistantMessage.id = data.assistant_message_id || assistantMessage.id
        assistantMessage.requestId = data.request_id
        errorMessage.value = data.message || '已停止生成。'
      },
    })
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
    if (!assistantMessage.content) {
      messages.value = messages.value.filter((message) => message.id !== assistantMessage.id)
    }
  } finally {
    assistantMessage.streaming = false
    sending.value = false
    activeController.value = null
    activeIdempotencyKey.value = ''
    stopping.value = false
    try {
      await refreshConversationList()
    } catch {
      // 回答已完成时，会话列表刷新失败不影响当前消息展示。
    }
    await scrollToBottom()
  }
}

async function stopGeneration() {
  if (!sending.value || stopping.value || !activeIdempotencyKey.value) return
  stopping.value = true
  try {
    const result = await stopConversationStream(
      activeConversationId.value,
      activeIdempotencyKey.value,
    )
    if (result.status !== 'stopping') activeController.value?.abort()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
    activeController.value?.abort()
  }
}

function handleKeydown(event) {
  if (event.isComposing) return
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    sendQuestion()
  }
}

onMounted(async () => {
  try {
    await refreshConversationList()
    if (conversations.value.length) await selectConversation(conversations.value[0].id)
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    loadingConversations.value = false
  }
})
</script>

<template>
  <section class="chat-page">
    <header class="chat-heading">
      <div>
        <span>KNOWLEDGE CHAT</span>
        <h1>知识库问答</h1>
        <p>为您提供专业医疗知识问答服务。</p>
      </div>
      <div class="knowledge-status"><i></i> 本地知识库已连接</div>
    </header>

    <div class="chat-workspace">
      <aside class="conversation-sidebar">
        <el-button type="primary" round class="new-chat-button" :disabled="sending" @click="startNewConversation">
          ＋ 新建会话
        </el-button>
        <div class="sidebar-title">历史会话</div>
        <div v-if="loadingConversations" class="sidebar-state">正在加载…</div>
        <div v-else-if="!conversations.length" class="sidebar-state">还没有历史会话</div>
        <div
          v-for="conversation in conversations"
          :key="conversation.id"
          class="conversation-item"
          :data-conversation-id="conversation.id"
          :class="{ active: conversation.id === activeConversationId }"
          @click="selectConversation(conversation.id)"
        >
          <button type="button" class="conversation-main" data-testid="conversation-main" :disabled="sending">
            <strong>{{ conversation.title }}</strong>
            <small>{{ conversation.message_count }} 条消息</small>
          </button>
          <button
            type="button"
            class="conversation-delete"
            data-testid="conversation-delete"
            :aria-label="`删除会话：${conversation.title}`"
            :disabled="sending"
            @click.stop="requestDelete(conversation)"
          >
            删除
          </button>
        </div>
      </aside>

      <div class="chat-panel">
        <div ref="messageArea" class="message-area" aria-live="polite">
          <div v-if="loadingMessages" class="message-loading">正在读取会话记录…</div>
          <article
            v-for="message in messages"
            v-else
            :key="message.id"
            class="message-row"
            :class="message.role"
          >
            <div class="avatar">{{ message.role === 'user' ? '你' : 'M' }}</div>
            <div class="message-body">
              <span class="role-name">{{ message.role === 'user' ? '我的问题' : '知识库助手' }}</span>
              <div class="bubble" data-testid="message-bubble" :class="{ thinking: message.streaming && !message.content }">
                <template v-if="message.content">
                  {{ message.content }}<i v-if="message.streaming" class="stream-cursor"></i>
                </template>
                <template v-else-if="message.streaming">
                  <i></i><i></i><i></i><span>正在检索资料并组织回答</span>
                </template>
              </div>
              <div v-if="message.sources?.length" class="sources">
                <button
                  type="button"
                  class="sources-toggle"
                  data-testid="sources-toggle"
                  :aria-expanded="message.sourcesExpanded ? 'true' : 'false'"
                  :aria-controls="`sources-${message.id}`"
                  @click="message.sourcesExpanded = !message.sourcesExpanded"
                >
                  <span>引用来源 · {{ message.sources.length }}</span>
                  <i :class="{ expanded: message.sourcesExpanded }">⌄</i>
                </button>
                <div v-if="message.sourcesExpanded" :id="`sources-${message.id}`" class="sources-list">
                  <details v-for="(source, index) in message.sources" :key="`${message.id}-${index}`">
                    <summary>
                      <span>{{ source.file_name }}</span>
                      <small>{{ source.page ? `第 ${source.page} 页` : '文本资料' }}</small>
                    </summary>
                    <p>{{ source.content }}</p>
                  </details>
                </div>
              </div>
              <div v-if="message.requestId" class="response-meta">请求标识：{{ message.requestId }}</div>
            </div>
          </article>
        </div>

        <div v-if="errorMessage" class="error-banner" role="alert">
          <span>{{ errorMessage }}</span>
          <button type="button" @click="errorMessage = ''">关闭</button>
        </div>
        <form class="composer" @submit.prevent="sendQuestion">
          <textarea
            v-model="question"
            maxlength="2000"
            rows="3"
            aria-label="输入知识库问题"
            placeholder="输入问题，Enter 发送，Shift + Enter 换行"
            :disabled="sending || loadingMessages"
            @keydown="handleKeydown"
          ></textarea>
          <div class="composer-footer">
            <span>{{ question.length }} / 2000</span>
            <el-button v-if="sending" type="danger" plain round :loading="stopping" :disabled="stopping" @click="stopGeneration">
              {{ stopping ? '正在停止' : '停止生成' }}
            </el-button>
            <el-button v-else type="primary" round native-type="submit" :disabled="!question.trim() || loadingMessages">发送问题</el-button>
          </div>
        </form>
        <p class="medical-note">回答仅用于学习和信息检索，不构成医疗建议。</p>
      </div>
    </div>

    <div v-if="deleteTarget" class="dialog-backdrop" @click.self="!deleting && (deleteTarget = null)">
      <div class="delete-dialog" role="dialog" aria-modal="true" aria-labelledby="conversation-delete-title">
        <div class="warning-mark">!</div>
        <h2 id="conversation-delete-title">确认删除会话？</h2>
        <p>“{{ deleteTarget.title }}”及其中的全部消息和引用来源都会被删除，此操作无法撤销。</p>
        <div>
          <el-button round :disabled="deleting" @click="deleteTarget = null">取消</el-button>
          <el-button type="danger" round :loading="deleting" @click="confirmDelete">确认删除</el-button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.chat-page { padding: 48px 0 56px; }
.chat-heading { display: flex; align-items: end; justify-content: space-between; gap: 24px; margin-bottom: 24px; }
.chat-heading span { color: var(--primary); font-size: 11px; font-weight: 800; letter-spacing: .16em; }
.chat-heading h1 { margin: 8px 0 6px; font-size: 34px; letter-spacing: -.04em; }
.chat-heading p { margin: 0; color: var(--muted); font-size: 14px; }
.knowledge-status { color: var(--muted); font-size: 13px; white-space: nowrap; }
.knowledge-status i { display: inline-block; width: 8px; height: 8px; margin-right: 7px; border-radius: 50%; background: #18a875; box-shadow: 0 0 0 5px rgba(24,168,117,.1); }
.chat-workspace { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: 16px; }
.conversation-sidebar, .chat-panel { border: 1px solid var(--line); border-radius: 20px; background: rgba(255,255,255,.9); box-shadow: 0 24px 60px rgba(35,87,77,.08); }
.conversation-sidebar { height: min(68vh, 680px); min-height: 520px; padding: 16px; overflow-y: auto; }
.new-chat-button { width: 100%; }
.sidebar-title { margin: 22px 8px 10px; color: var(--muted); font-size: 11px; font-weight: 800; letter-spacing: .08em; }
.sidebar-state { padding: 22px 8px; color: #91a09d; font-size: 12px; text-align: center; }
.conversation-item { width: 100%; display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 6px; margin-bottom: 6px; padding: 5px; border-radius: 12px; color: var(--ink); background: transparent; cursor: pointer; }
.conversation-item:hover { background: #f1f6f4; }
.conversation-item.active { color: var(--primary-dark); background: #e8f3ef; }
.conversation-main { min-width: 0; display: grid; gap: 5px; padding: 7px; border: 0; color: inherit; background: transparent; text-align: left; cursor: pointer; }
.conversation-main:disabled, .conversation-delete:disabled { cursor: not-allowed; opacity: .65; }
.conversation-main strong { overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.conversation-main small { color: var(--muted); font-size: 10px; }
.conversation-delete { padding: 6px 7px; border: 0; border-radius: 7px; color: #ad5547; background: transparent; font-size: 10px; cursor: pointer; opacity: 0; }
.conversation-item:hover .conversation-delete, .conversation-item:focus-within .conversation-delete { opacity: 1; }
.chat-panel { min-width: 0; overflow: hidden; }
.message-area { height: min(52vh, 530px); min-height: 380px; overflow-y: auto; padding: 32px; scroll-behavior: smooth; }
.message-loading { display: grid; height: 100%; place-items: center; color: var(--muted); font-size: 13px; }
.message-row { display: flex; gap: 13px; margin-bottom: 28px; }
.message-row.user { flex-direction: row-reverse; }
.avatar { flex: 0 0 34px; height: 34px; display: grid; place-items: center; border-radius: 11px; color: white; background: var(--primary); font-size: 13px; font-weight: 800; }
.user .avatar { color: var(--ink); background: #e6eeeb; }
.message-body { max-width: min(78%, 760px); }
.user .message-body { text-align: right; }
.role-name { display: block; margin: 0 4px 7px; color: var(--muted); font-size: 11px; }
.bubble { padding: 15px 17px; border-radius: 6px 17px 17px 17px; color: #29433e; background: #f1f6f4; line-height: 1.75; white-space: pre-wrap; text-align: left; }
.user .bubble { color: white; background: var(--primary); border-radius: 17px 6px 17px 17px; }
.sources { margin-top: 12px; text-align: left; }
.sources-toggle { width: 100%; display: flex; align-items: center; justify-content: space-between; padding: 3px 0 8px; border: 0; color: var(--muted); background: transparent; font: inherit; font-size: 12px; font-weight: 700; text-align: left; cursor: pointer; }
.sources-toggle i { font-style: normal; font-size: 16px; transition: transform .2s ease; }
.sources-toggle i.expanded { transform: rotate(180deg); }
details { margin-top: 7px; overflow: hidden; border: 1px solid var(--line); border-radius: 11px; background: #fff; }
summary { display: flex; justify-content: space-between; gap: 12px; padding: 11px 13px; cursor: pointer; color: var(--ink); font-size: 13px; }
summary small { color: var(--muted); white-space: nowrap; }
details p { margin: 0; padding: 0 13px 13px; color: var(--muted); font-size: 13px; line-height: 1.7; }
.response-meta { margin-top: 8px; color: #91a09d; font-size: 10px; }
.thinking { display: flex; align-items: center; gap: 5px; color: var(--muted); }
.thinking i { width: 6px; height: 6px; border-radius: 50%; background: var(--primary); animation: pulse 1.1s infinite alternate; }
.thinking i:nth-child(2) { animation-delay: .2s; }
.thinking i:nth-child(3) { animation-delay: .4s; }
.thinking span { margin-left: 5px; font-size: 13px; }
.stream-cursor { display: inline-block; width: 2px; height: 1em; margin-left: 3px; vertical-align: -2px; background: var(--primary); animation: blink .8s infinite; }
@keyframes pulse { to { opacity: .25; transform: translateY(-2px); } }
@keyframes blink { 50% { opacity: 0; } }
.error-banner { display: flex; justify-content: space-between; gap: 16px; margin: 0 24px 12px; padding: 11px 14px; border-radius: 10px; color: #a33f2f; background: #fff0ed; font-size: 13px; }
.error-banner button { border: 0; color: inherit; background: transparent; cursor: pointer; }
.composer { margin: 0 24px 10px; padding: 14px; border: 1px solid var(--line); border-radius: 16px; background: #fbfdfc; }
textarea { width: 100%; resize: none; border: 0; outline: 0; color: var(--ink); background: transparent; font: inherit; line-height: 1.6; }
textarea::placeholder { color: #9aaba7; }
.composer-footer { display: flex; align-items: center; justify-content: space-between; margin-top: 6px; }
.composer-footer span { color: #9aaba7; font-size: 11px; }
.medical-note { margin: 0 0 16px; color: #91a09d; text-align: center; font-size: 11px; }
.dialog-backdrop { position: fixed; inset: 0; z-index: 20; display: grid; place-items: center; padding: 20px; background: rgba(18,39,34,.45); backdrop-filter: blur(4px); }
.delete-dialog { width: min(420px, 100%); padding: 28px; border-radius: 20px; background: white; box-shadow: 0 24px 80px rgba(0,0,0,.2); text-align: center; }
.warning-mark { width: 44px; height: 44px; display: grid; place-items: center; margin: 0 auto 14px; border-radius: 50%; color: #bd4b39; background: #fff0ed; font-size: 22px; font-weight: 800; }
.delete-dialog h2 { margin: 0; font-size: 20px; }
.delete-dialog p { margin: 12px 0 22px; color: var(--muted); font-size: 13px; line-height: 1.7; }
.delete-dialog > div:last-child { display: flex; justify-content: center; gap: 10px; }
@media (max-width: 800px) {
  .chat-workspace { grid-template-columns: 1fr; }
  .conversation-sidebar { height: auto; min-height: 0; max-height: 220px; }
  .conversation-delete { opacity: 1; }
}
@media (max-width: 700px) {
  .chat-page { padding-top: 28px; }
  .chat-heading { align-items: start; flex-direction: column; }
  .message-area { min-height: 360px; padding: 20px 14px; }
  .message-body { max-width: calc(100% - 47px); }
  .composer { margin-inline: 12px; }
}
</style>
