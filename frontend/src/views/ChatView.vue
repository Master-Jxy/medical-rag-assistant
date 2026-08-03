<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import {
  ChevronDown,
  History,
  LoaderCircle,
  PanelLeft,
  Plus,
  Send,
  Square,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  X,
} from '@lucide/vue'

import {
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  markConversationRead,
  stopConversationStream,
  streamConversation,
} from '../api/conversations.js'
import { scrollToLatest } from '../utils/scroll.js'
import { getApiErrorMessage } from '../api/http.js'
import { submitAnswerFeedback } from '../api/quality.js'
import { getDocumentTrace, openDocumentPreview } from '../api/citations.js'
import MarkdownContent from '../components/MarkdownContent.vue'
import ModelSelector from '../components/ModelSelector.vue'
import UsageMeta from '../components/UsageMeta.vue'
import { createUuid } from '../utils/uuid.js'
import { useConversationStreamRegistry } from '../features/agent-chat/useConversationStreamRegistry.js'

const WELCOME_MESSAGE = {
  id: 'welcome',
  role: 'assistant',
  content: '你好，我会根据已上传的知识库资料回答问题，并展示引用来源。',
  sources: [],
}

const question = ref('')
const questionInput = ref(null)
const loadingConversations = ref(true)
const loadingMessages = ref(false)
const errorMessage = ref('')
const conversations = ref([])
const activeConversationId = ref('')
const messageCache = reactive(new Map())
const streamRegistry = useConversationStreamRegistry('rag')
const messages = computed(() => (
  streamRegistry.get(activeConversationId.value)?.messages
    || messageCache.get(activeConversationId.value)
    || [{ ...WELCOME_MESSAGE }]
))
const activeConversation = computed(() => conversations.value.find(
  (item) => item.id === activeConversationId.value,
) || null)
const sending = computed(() => streamRegistry.isRunning(
  activeConversationId.value,
  activeConversation.value?.run_status,
))
const stopping = computed(() => streamRegistry.get(activeConversationId.value)?.phase === 'stopping')
const messageArea = ref(null)
const deleteTarget = ref(null)
const deleting = ref(false)
const mobileHistoryOpen = ref(false)
const feedbackTarget = ref(null)
const feedbackSubmitting = ref(false)
let selectionVersion = 0
let disposed = false
const feedbackForm = reactive({
  rating: 'up',
  questionCategory: 'general',
  issueCategory: 'other',
  comment: '',
})

function mapStoredMessage(message) {
  let content = message.content
  if (message.role === 'assistant' && !content) {
    if (message.status === 'failed') content = '本次回答失败，请重新提问。'
    if (message.status === 'pending') content = '上次回答未正常结束，请重新提问。'
    if (message.status === 'stopped') content = '回答已停止。'
  }
  return {
    id: message.id,
    sequence: Number(message.sequence || 0),
    role: message.role,
    content,
    sources: message.sources || [],
    sourcesExpanded: false,
    requestId: message.request_id,
    status: message.status,
    usage: message.usage || null,
    feedbackRating: null,
  }
}

function findConversation(conversationId) {
  return conversations.value.find((item) => item.id === conversationId) || null
}

function updateConversationSummary(conversationId, changes) {
  const conversation = findConversation(conversationId)
  if (conversation) Object.assign(conversation, changes)
}

function maxReadableSequence(rows) {
  return rows.reduce((maximum, row) => (
    ['completed', 'failed', 'stopped'].includes(row.status)
      ? Math.max(maximum, Number(row.sequence || 0))
      : maximum
  ), 0)
}

async function markConversationSeen(conversationId, rows) {
  const sequence = maxReadableSequence(rows)
  if (!sequence) return
  const result = await markConversationRead(conversationId, sequence)
  updateConversationSummary(conversationId, {
    last_read_sequence: result.last_read_sequence,
    has_unread: false,
  })
  streamRegistry.clearUnread(conversationId)
}

function conversationIsRunning(conversation) {
  return streamRegistry.isRunning(conversation.id, conversation.run_status)
}

function conversationHasUnread(conversation) {
  return streamRegistry.hasUnread(conversation.id, conversation.has_unread)
}

function openFeedback(message, rating) {
  if (!message.id || message.id === 'welcome' || message.streaming) return
  feedbackTarget.value = message
  feedbackForm.rating = rating
  feedbackForm.questionCategory = 'general'
  feedbackForm.issueCategory = 'other'
  feedbackForm.comment = ''
}

async function submitFeedback() {
  if (!feedbackTarget.value || feedbackSubmitting.value) return
  feedbackSubmitting.value = true
  try {
    const feedback = await submitAnswerFeedback(feedbackTarget.value.id, {
      rating: feedbackForm.rating,
      question_category: feedbackForm.questionCategory,
      issue_category: feedbackForm.rating === 'down' ? feedbackForm.issueCategory : null,
      comment: feedbackForm.comment.trim() || null,
    })
    feedbackTarget.value.feedbackRating = feedback.rating
    feedbackTarget.value = null
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    feedbackSubmitting.value = false
  }
}

async function inspectSource(source) {
  if (!source.document_id) return
  try {
    source.trace = source.trace || await getDocumentTrace(source.document_id)
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  }
}

async function openSource(source) {
  try { await openDocumentPreview(source.document_id, source.page) }
  catch (error) { errorMessage.value = getApiErrorMessage(error) }
}

function scrollToBottom() {
  return scrollToLatest(messageArea)
}

async function focusQuestionInput() {
  await nextTick()
  resizeQuestionInput()
  if (!sending.value && !loadingMessages.value) questionInput.value?.focus()
}

function resizeQuestionInput() {
  const input = questionInput.value
  if (!input) return
  input.style.height = 'auto'
  const lineHeight = Number.parseFloat(window.getComputedStyle(input).lineHeight) || 22
  const maxHeight = lineHeight * 4
  const nextHeight = Math.min(input.scrollHeight, maxHeight)
  input.style.height = `${Math.max(lineHeight, nextHeight)}px`
  input.style.overflowY = input.scrollHeight > maxHeight ? 'auto' : 'hidden'
}

async function refreshConversationList() {
  const data = await listConversations()
  conversations.value = data.conversations.map((item) => ({ ...item }))
}

async function loadConversation(
  conversationId,
  { markAsRead = false, preserveCache = false } = {},
) {
  const conversation = await getConversation(conversationId)
  const rows = conversation.messages.map(mapStoredMessage)
  const existing = preserveCache ? messageCache.get(conversationId) || [] : []
  const merged = [...rows]
  for (const message of existing) {
    if (message.id !== 'welcome' && !merged.some((item) => item.id === message.id)) {
      merged.push(message)
    }
  }
  messageCache.set(conversationId, merged.length ? merged : [{ ...WELCOME_MESSAGE }])
  const liveEntry = streamRegistry.get(conversationId)
  if (liveEntry?.messages) {
    for (const stored of rows) {
      const live = liveEntry.messages.find((item) => item.id === stored.id)
      if (live && (stored.content || ['completed', 'failed', 'stopped'].includes(stored.status))) {
        Object.assign(live, stored)
      }
    }
  }
  updateConversationSummary(conversationId, conversation)
  if (markAsRead) await markConversationSeen(conversationId, rows)
  return conversation
}

async function selectConversation(conversationId) {
  if (conversationId === activeConversationId.value) {
    await focusQuestionInput()
    return
  }
  const version = ++selectionVersion
  activeConversationId.value = conversationId
  errorMessage.value = ''
  loadingMessages.value = true
  try {
    await loadConversation(conversationId, { markAsRead: true })
    streamRegistry.clearUnread(conversationId)
  } catch (error) {
    if (version === selectionVersion) errorMessage.value = getApiErrorMessage(error)
  } finally {
    if (version === selectionVersion) {
      loadingMessages.value = false
      mobileHistoryOpen.value = false
      await scrollToBottom()
      await focusQuestionInput()
    }
  }
}

async function startNewConversation() {
  errorMessage.value = ''
  try {
    const conversation = await createConversation()
    conversations.value.unshift(conversation)
    activeConversationId.value = conversation.id
    messageCache.set(conversation.id, [{ ...WELCOME_MESSAGE }])
    mobileHistoryOpen.value = false
    await focusQuestionInput()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  }
}

function requestDelete(conversation) {
  if (conversationIsRunning(conversation)) {
    errorMessage.value = '该会话仍在生成，请先打开会话并停止回答后再删除。'
    return
  }
  deleteTarget.value = conversation
  errorMessage.value = ''
}

async function confirmDelete() {
  if (!deleteTarget.value || deleting.value) return
  const target = deleteTarget.value
  if (conversationIsRunning(target)) {
    errorMessage.value = '该会话仍在生成，请先停止回答后再删除。'
    deleteTarget.value = null
    return
  }
  const deletingActiveConversation = target.id === activeConversationId.value
  deleting.value = true
  errorMessage.value = ''

  try {
    await deleteConversation(target.id)
    conversations.value = conversations.value.filter((item) => item.id !== target.id)
    messageCache.delete(target.id)
    streamRegistry.remove(target.id)
    deleteTarget.value = null

    if (deletingActiveConversation) {
      activeConversationId.value = ''
      if (conversations.value.length) {
        await selectConversation(conversations.value[0].id)
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
  messageCache.set(conversation.id, [{ ...WELCOME_MESSAGE }])
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

  let conversationMessages = messageCache.get(conversationId)
  if (!conversationMessages || (
    conversationMessages.length === 1 && conversationMessages[0].id === 'welcome'
  )) {
    conversationMessages = []
    messageCache.set(conversationId, conversationMessages)
  }
  const userMessage = reactive({
    id: createUuid(),
    role: 'user',
    content: cleanedQuestion,
    sources: [],
  })
  const assistantMessage = reactive({
    id: createUuid(),
    role: 'assistant',
    content: '',
    sources: [],
    streaming: true,
    sourcesExpanded: false,
    status: 'pending',
    feedbackRating: null,
  })
  conversationMessages.push(userMessage, assistantMessage)
  question.value = ''
  nextTick(resizeQuestionInput)
  const idempotencyKey = createUuid()
  let entry
  try {
    entry = streamRegistry.start(conversationId, {
      phase: 'running',
      requestId: idempotencyKey,
      messages: conversationMessages,
    })
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
    return
  }
  await scrollToBottom()
  let terminalReceived = false

  try {
    await streamConversation(conversationId, cleanedQuestion, {
      idempotencyKey,
      signal: entry.controller.signal,
      onToken(content) {
        assistantMessage.content += content
        if (activeConversationId.value === conversationId) scrollToBottom()
      },
      onSources(sources) {
        assistantMessage.sources = sources
      },
      onDone(data) {
        if (terminalReceived) return
        terminalReceived = true
        userMessage.id = data.user_message_id || userMessage.id
        assistantMessage.id = data.assistant_message_id || assistantMessage.id
        assistantMessage.requestId = data.request_id
        assistantMessage.disclaimer = data.disclaimer
        assistantMessage.status = 'completed'
        assistantMessage.usage = data.usage || null
        entry.phase = 'settling'
      },
      onStopped(data) {
        if (terminalReceived) return
        terminalReceived = true
        userMessage.id = data.user_message_id || userMessage.id
        assistantMessage.id = data.assistant_message_id || assistantMessage.id
        assistantMessage.requestId = data.request_id
        if (activeConversationId.value === conversationId) {
          errorMessage.value = data.message || '已停止生成。'
        }
        assistantMessage.status = 'stopped'
        entry.phase = 'settling'
      },
    })
  } catch (error) {
    if (error?.name !== 'AbortError' && activeConversationId.value === conversationId) {
      errorMessage.value = getApiErrorMessage(error)
    }
    entry.error = getApiErrorMessage(error)
    entry.phase = error?.name === 'AbortError' ? 'stopped' : 'failed'
    if (activeConversationId.value !== conversationId) streamRegistry.markUnread(conversationId)
    if (!assistantMessage.content) {
      const index = conversationMessages.findIndex((message) => message.id === assistantMessage.id)
      if (index >= 0) conversationMessages.splice(index, 1)
    }
  } finally {
    assistantMessage.streaming = false
    if (entry.phase === 'settling') entry.phase = assistantMessage.status
    else if (['running', 'stopping'].includes(entry.phase)) entry.phase = 'completed'
    entry.controller = null
    if (!disposed) {
      try {
        await refreshConversationList()
      } catch {
        // 回答已完成时，会话列表刷新失败不影响当前消息展示。
      }
      const isCurrent = activeConversationId.value === conversationId
      try {
        await loadConversation(conversationId, {
          markAsRead: isCurrent,
          preserveCache: true,
        })
      } catch {
        // 已有流式缓存可继续展示，读取持久化结果失败时等待下次打开会话恢复。
      }
      if (isCurrent) {
        streamRegistry.clearUnread(conversationId)
        await scrollToBottom()
        await focusQuestionInput()
      } else {
        streamRegistry.markUnread(conversationId)
      }
    }
  }
}

async function stopGeneration() {
  const conversationId = activeConversationId.value
  let entry = streamRegistry.get(conversationId)
  const requestId = entry?.requestId || activeConversation.value?.active_run_id || ''
  if (!sending.value || stopping.value || !requestId) return
  if (!entry) {
    entry = streamRegistry.start(conversationId, {
      phase: 'stopping',
      requestId,
      controller: null,
    })
  } else {
    entry.phase = 'stopping'
  }
  try {
    const result = await stopConversationStream(
      conversationId,
      requestId,
    )
    if (result.status !== 'stopping') streamRegistry.abort(conversationId)
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
    streamRegistry.abort(conversationId)
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
    await focusQuestionInput()
  }
})

onBeforeUnmount(() => {
  disposed = true
})
</script>

<template>
  <section class="chat-page">
    <header class="chat-heading">
      <div>
        <span>KNOWLEDGE CHAT</span>
        <h1>知识库问答</h1>
        <p>基于已发布医学资料检索回答，并保留可追溯来源。</p>
      </div>
      <div class="chat-heading-actions">
        <button
          type="button"
          class="mobile-history-button"
          aria-label="打开历史会话"
          @click="mobileHistoryOpen = true"
        ><PanelLeft :size="17" />历史会话</button>
        <div class="knowledge-status"><i></i> 知识库在线</div>
      </div>
    </header>

    <div class="chat-workspace">
      <button
        v-if="mobileHistoryOpen"
        type="button"
        class="history-backdrop"
        aria-label="关闭历史会话"
        @click="mobileHistoryOpen = false"
      />
      <aside class="conversation-sidebar" :class="{ 'mobile-open': mobileHistoryOpen }">
        <div class="conversation-sidebar-head">
          <strong><History :size="16" />会话</strong>
          <button type="button" class="mobile-close-button" aria-label="关闭历史会话" @click="mobileHistoryOpen = false"><X :size="17" /></button>
        </div>
        <el-button type="primary" round class="new-chat-button" @click="startNewConversation">
          <Plus :size="16" />新建会话
        </el-button>
        <div class="sidebar-title">历史会话</div>
        <div v-if="loadingConversations" class="sidebar-state">正在加载…</div>
        <div v-else-if="!conversations.length" class="sidebar-state">还没有历史会话</div>
        <div
          v-for="conversation in conversations"
          :key="conversation.id"
          class="conversation-item"
          :data-conversation-id="conversation.id"
          :class="{
            active: conversation.id === activeConversationId,
            running: conversationIsRunning(conversation),
          }"
          @click="selectConversation(conversation.id)"
        >
          <button type="button" class="conversation-main" data-testid="conversation-main">
            <span class="conversation-name">
              <strong>{{ conversation.title }}</strong>
              <LoaderCircle
                v-if="conversationIsRunning(conversation)"
                class="conversation-spinner"
                :size="14"
                aria-label="正在生成"
              />
              <i
                v-else-if="conversationHasUnread(conversation)"
                class="conversation-unread"
                aria-label="有未读回答"
              ></i>
            </span>
            <small>{{ conversation.message_count }} 条消息</small>
          </button>
          <button
            type="button"
            class="conversation-delete"
            data-testid="conversation-delete"
            :aria-label="`删除会话：${conversation.title}`"
            :disabled="conversationIsRunning(conversation)"
            :title="conversationIsRunning(conversation) ? '请先停止当前会话' : ''"
            @click.stop="requestDelete(conversation)"
          >
            <Trash2 :size="14" />
          </button>
        </div>
      </aside>

      <div class="chat-panel">
        <div
          ref="messageArea"
          class="message-area"
          data-testid="rag-message-area"
          aria-live="polite"
        >
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
                  <MarkdownContent
                    v-if="message.role === 'assistant'"
                    :content="message.content"
                    :streaming="message.streaming"
                  />
                  <template v-else>{{ message.content }}</template>
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
                    <ChevronDown :size="15" :class="{ expanded: message.sourcesExpanded }" />
                </button>
                <div v-if="message.sourcesExpanded" :id="`sources-${message.id}`" class="sources-list">
                  <details v-for="(source, index) in message.sources" :key="`${message.id}-${index}`">
                    <summary>
                      <span>{{ source.file_name }}</span>
                      <small>{{ source.page ? `第 ${source.page} 页` : '文本资料' }}</small>
                    </summary>
                    <p>{{ source.content }}</p>
                    <div v-if="source.document_id" class="source-actions">
                      <button @click="openSource(source)">{{ source.page ? `打开第 ${source.page} 页` : '打开原文' }}</button>
                      <button @click="inspectSource(source)">版本与来源</button>
                    </div>
                    <p v-if="source.trace" class="source-trace">
                      版本 {{ source.trace.version }} · {{ source.trace.source || '未标注来源' }} ·
                      {{ source.trace.category || '未分类' }} · {{ source.trace.department || '未指定科室' }} ·
                      {{ source.trace.tags.join('、') || '无标签' }} · 复核状态 {{ source.trace.review_status }}
                    </p>
                  </details>
                </div>
              </div>
              <div v-if="message.requestId" class="response-meta">请求标识：{{ message.requestId }}</div>
              <UsageMeta v-if="message.role === 'assistant' && !message.streaming" :usage="message.usage" />
              <div v-if="message.role === 'assistant' && message.id !== 'welcome' && !message.streaming && message.status === 'completed'" class="answer-feedback" aria-label="回答反馈">
                <span>这条回答有帮助吗？</span>
                <button type="button" aria-label="回答有帮助" :class="{ active: message.feedbackRating === 'up' }" @click="openFeedback(message, 'up')"><ThumbsUp :size="14" /></button>
                <button type="button" aria-label="回答需改进" :class="{ active: message.feedbackRating === 'down' }" @click="openFeedback(message, 'down')"><ThumbsDown :size="14" /></button>
              </div>
            </div>
          </article>
        </div>

        <div v-if="errorMessage" class="error-banner" role="alert">
          <span>{{ errorMessage }}</span>
          <button type="button" @click="errorMessage = ''">关闭</button>
        </div>
        <form class="composer" @submit.prevent="sendQuestion">
          <textarea
            ref="questionInput"
            v-model="question"
            maxlength="2000"
            rows="1"
            aria-label="输入知识库问题"
            placeholder="输入问题，Enter 发送，Shift + Enter 换行"
            :disabled="sending || loadingMessages"
            @input="resizeQuestionInput"
            @keydown="handleKeydown"
          ></textarea>
          <div class="composer-footer">
            <ModelSelector surface="rag" />
            <div class="composer-actions">
              <span v-if="question.length">{{ question.length }} / 2000</span>
              <el-button v-if="sending" data-testid="stop-generation" type="danger" plain round :loading="stopping" :disabled="stopping" @click="stopGeneration">
                <Square v-if="!stopping" :size="14" />{{ stopping ? '正在停止' : '停止生成' }}
              </el-button>
              <el-button v-else type="primary" round native-type="submit" :disabled="!question.trim() || loadingMessages"><Send :size="15" />发送</el-button>
            </div>
          </div>
        </form>
        <p class="medical-note">回答仅用于学习和信息检索，不构成医疗建议。</p>
      </div>
    </div>

    <div v-if="feedbackTarget" class="dialog-backdrop" @click.self="!feedbackSubmitting && (feedbackTarget = null)">
      <form class="feedback-dialog" role="dialog" aria-modal="true" aria-labelledby="feedback-title" @submit.prevent="submitFeedback">
        <header>
          <div><span>回答反馈</span><h2 id="feedback-title">{{ feedbackForm.rating === 'up' ? '这条回答有帮助' : '帮助我们改进回答' }}</h2></div>
          <button type="button" aria-label="关闭反馈" :disabled="feedbackSubmitting" @click="feedbackTarget = null"><X :size="18" /></button>
        </header>
        <label>问题分类
          <select v-model="feedbackForm.questionCategory">
            <option value="general">其他</option><option value="symptom">症状</option><option value="medication">用药</option>
            <option value="test">检查</option><option value="emergency">急症</option><option value="prevention">预防</option>
          </select>
        </label>
        <label v-if="feedbackForm.rating === 'down'">需要改进的方面
          <select v-model="feedbackForm.issueCategory">
            <option value="inaccurate">不准确</option><option value="irrelevant">不相关</option><option value="incomplete">不完整</option>
            <option value="unsafe">不安全</option><option value="citation">引用问题</option><option value="other">其他</option>
          </select>
        </label>
        <label>补充说明（可选）
          <textarea v-model="feedbackForm.comment" rows="3" maxlength="500" placeholder="说明哪些内容对你有帮助，或哪里需要改进"></textarea>
        </label>
        <footer><el-button :disabled="feedbackSubmitting" @click="feedbackTarget = null">取消</el-button><el-button type="primary" native-type="submit" :loading="feedbackSubmitting">提交反馈</el-button></footer>
      </form>
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
.chat-page { height: 100%; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.chat-heading { display: none; min-height: 56px; align-items: center; flex: 0 0 auto; margin-bottom: 10px; padding: 8px 14px; border-radius: 18px; }
.chat-heading > div:first-child > span, .chat-heading p { display: none; }
.chat-heading h1 { margin: 0; font-size: 18px; line-height: 28px; }
.chat-heading-actions { display: flex; align-items: center; gap: 10px; }
.knowledge-status { display: inline-flex; align-items: center; padding: 6px 9px; border: 1px solid var(--line); border-radius: 6px; color: var(--muted); background: #fff; font-size: 11px; white-space: nowrap; }
.knowledge-status i { width: 7px; height: 7px; margin-right: 6px; border-radius: 50%; background: var(--success); }
.mobile-history-button, .mobile-close-button { display: none; }
.chat-workspace { min-height: 0; flex: 1; display: grid; grid-template-columns: 250px minmax(0, 1fr); gap: 10px; overflow: hidden; }
.conversation-sidebar, .chat-panel { border: 1px solid var(--line); border-radius: 8px; background: #fff; }
.conversation-sidebar { min-height: 0; max-height: 100%; padding: 12px; overflow-y: auto; }
.conversation-sidebar-head { min-height: 32px; display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; padding: 0 5px; }
.conversation-sidebar-head strong { display: flex; align-items: center; gap: 7px; color: var(--ink); font-size: 12px; }
.new-chat-button { width: 100%; }
.sidebar-title { margin: 18px 8px 7px; color: var(--muted); font-size: 10px; font-weight: 700; letter-spacing: 0; }
.sidebar-state { padding: 22px 8px; color: #91a09d; font-size: 12px; text-align: center; }
.conversation-item { width: 100%; display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 4px; margin-bottom: 3px; padding: 3px; border-radius: 6px; color: var(--ink); background: transparent; cursor: pointer; }
.conversation-item:hover { background: var(--bg-subtle); }
.conversation-item.active { color: var(--primary-dark); background: #e8f3ef; box-shadow: inset 2px 0 var(--brand); }
.conversation-main { min-width: 0; display: grid; gap: 5px; padding: 7px; border: 0; color: inherit; background: transparent; text-align: left; cursor: pointer; }
.conversation-main:disabled, .conversation-delete:disabled { cursor: not-allowed; opacity: .65; }
.conversation-name { min-width: 0; display: flex; align-items: center; gap: 7px; }
.conversation-main strong { min-width: 0; flex: 1; overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.conversation-spinner { flex: 0 0 auto; color: var(--primary); animation: conversation-spin .8s linear infinite; }
.conversation-unread { flex: 0 0 auto; width: 7px; height: 7px; border-radius: 50%; background: var(--action); box-shadow: 0 0 0 3px rgba(44, 103, 214, .12); }
.conversation-main small { color: var(--muted); font-size: 10px; }
.conversation-delete { width: 28px; height: 28px; display: grid; place-items: center; padding: 0; border: 0; border-radius: 5px; color: var(--danger); background: transparent; cursor: pointer; opacity: 0; }
.conversation-item:hover .conversation-delete, .conversation-item:focus-within .conversation-delete { opacity: 1; }
@keyframes conversation-spin { to { transform: rotate(360deg); } }
.chat-panel { min-width: 0; min-height: 0; height: 100%; display: grid; grid-template-rows: minmax(0, 1fr) auto auto; overflow: hidden; }
.message-area { min-height: 0; overflow-y: auto; padding: 16px clamp(16px, 3vw, 40px); scroll-behavior: smooth; }
.message-loading { display: grid; height: 100%; place-items: center; color: var(--muted); font-size: 13px; }
.message-row { display: flex; gap: 10px; max-width: 960px; margin: 0 auto 18px; }
.message-row.user { flex-direction: row-reverse; }
.avatar { flex: 0 0 32px; height: 32px; display: grid; place-items: center; border-radius: 6px; color: white; background: var(--primary); font-size: 12px; font-weight: 700; }
.user .avatar { color: #fff; background: #355d7a; }
.message-body { max-width: min(82%, 820px); min-width: 0; }
.user .message-body { text-align: right; }
.role-name { display: block; margin: 0 2px 6px; color: var(--muted); font-size: 10px; }
.bubble { padding: 11px 13px; border: 1px solid #e1e8e6; border-radius: 8px; color: #29433e; background: var(--bg-subtle); font-size: 13px; line-height: 1.62; white-space: pre-wrap; text-align: left; }
.user .bubble { color: #fff; border-color: #355d7a; background: #355d7a; }
.sources { margin-top: 12px; text-align: left; }
.sources-toggle { width: 100%; display: flex; align-items: center; justify-content: space-between; padding: 3px 0 8px; border: 0; color: var(--muted); background: transparent; font: inherit; font-size: 12px; font-weight: 700; text-align: left; cursor: pointer; }
.sources-toggle svg { transition: transform .2s ease; }
.sources-toggle svg.expanded { transform: rotate(180deg); }
.answer-feedback { display: flex; align-items: center; gap: 6px; margin-top: 9px; color: var(--muted); font-size: 12px; }
.answer-feedback button { width: 28px; height: 28px; display: grid; place-items: center; padding: 0; border: 1px solid var(--border); border-radius: 5px; color: var(--muted); background: #fff; cursor: pointer; }
.answer-feedback button.active { border-color: var(--primary); background: #eff8f4; }
.source-actions { display: flex; gap: 8px; margin-top: 8px; }
.source-actions button { border: 0; padding: 0; background: none; color: var(--primary); cursor: pointer; }
.source-trace { color: var(--muted); font-size: 12px; }
details { margin-top: 7px; overflow: hidden; border: 1px solid var(--line); border-radius: 6px; background: #fff; }
summary { display: flex; justify-content: space-between; gap: 12px; padding: 11px 13px; cursor: pointer; color: var(--ink); font-size: 13px; }
summary small { color: var(--muted); white-space: nowrap; }
details p { margin: 0; padding: 0 13px 13px; color: var(--muted); font-size: 13px; line-height: 1.7; }
.response-meta { margin-top: 8px; color: #91a09d; font-size: 10px; }
.thinking { display: flex; align-items: center; gap: 5px; color: var(--muted); }
.thinking i { width: 6px; height: 6px; border-radius: 50%; background: var(--primary); animation: pulse 1.1s infinite alternate; }
.thinking i:nth-child(2) { animation-delay: .2s; }
.thinking i:nth-child(3) { animation-delay: .4s; }
.thinking span { margin-left: 5px; font-size: 13px; }
@keyframes pulse { to { opacity: .25; transform: translateY(-2px); } }
.error-banner { display: flex; justify-content: space-between; gap: 16px; margin: 0 24px 10px; padding: 10px 13px; border: 1px solid #f0c4c0; border-radius: 6px; color: #a33f2f; background: #fff7f6; font-size: 12px; }
.error-banner button { border: 0; color: inherit; background: transparent; cursor: pointer; }
.composer { width: min(calc(100% - 36px), 960px); display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: end; gap: 10px; margin: 0 auto 7px; padding: 8px 10px; border: 1px solid var(--border-strong); border-radius: 8px; background: #fff; box-shadow: 0 8px 24px rgba(23,32,30,.08); }
textarea { width: 100%; min-height: 22px; max-height: 88px; align-self: center; resize: none; overflow-y: hidden; border: 0; outline: 0; color: var(--ink); background: transparent; font: inherit; font-size: 13px; line-height: 22px; }
textarea::placeholder { color: #9aaba7; }
.composer-footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin: 0; }
.composer-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; }
.composer-footer span { color: #9aaba7; font-size: 11px; }
.medical-note { margin: 0 0 10px; color: #91a09d; text-align: center; font-size: 10px; }
.dialog-backdrop { position: fixed; inset: 0; z-index: 60; display: grid; place-items: center; padding: 20px; background: rgba(18,39,34,.5); }
.delete-dialog { width: min(420px, 100%); padding: 24px; border-radius: 8px; background: white; box-shadow: 0 24px 70px rgba(0,0,0,.22); text-align: center; }
.warning-mark { width: 44px; height: 44px; display: grid; place-items: center; margin: 0 auto 14px; border-radius: 50%; color: #bd4b39; background: #fff0ed; font-size: 22px; font-weight: 800; }
.delete-dialog h2 { margin: 0; font-size: 20px; }
.delete-dialog p { margin: 12px 0 22px; color: var(--muted); font-size: 13px; line-height: 1.7; }
.delete-dialog > div:last-child { display: flex; justify-content: center; gap: 10px; }
.feedback-dialog { width: min(520px, 100%); display: grid; gap: 15px; padding: 22px; border-radius: 8px; background: #fff; box-shadow: 0 24px 70px rgba(0,0,0,.22); }
.feedback-dialog header { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.feedback-dialog header span { color: var(--brand); font-size: 10px; font-weight: 700; }
.feedback-dialog h2 { margin: 3px 0 0; color: var(--ink); font-size: 18px; }
.feedback-dialog header button { width: 32px; height: 32px; display: grid; place-items: center; border: 0; border-radius: 5px; color: var(--muted); background: transparent; cursor: pointer; }
.feedback-dialog header button:hover { background: var(--bg-subtle); }
.feedback-dialog label { display: grid; gap: 6px; color: var(--ink); font-size: 12px; font-weight: 600; }
.feedback-dialog select, .feedback-dialog textarea { width: 100%; padding: 9px 10px; border: 1px solid var(--line); border-radius: 6px; outline: 0; background: #fff; font-weight: 400; }
.feedback-dialog textarea { min-height: 84px; resize: vertical; }
.feedback-dialog select:focus, .feedback-dialog textarea:focus { border-color: var(--action); box-shadow: 0 0 0 3px #e7efff; }
.feedback-dialog footer { display: flex; justify-content: flex-end; gap: 8px; padding-top: 2px; }
.history-backdrop { display: none; }
@media (max-width: 800px) {
  .chat-heading { display: flex; }
  .chat-page { padding: 12px; }
  .mobile-history-button { display: inline-flex; align-items: center; gap: 6px; min-height: 34px; padding: 0 10px; border: 1px solid var(--line); border-radius: 6px; color: var(--ink); background: #fff; font-size: 12px; cursor: pointer; }
  .chat-workspace { display: block; min-height: 0; flex: 1; }
  .conversation-sidebar { position: fixed; top: 0; bottom: 0; left: 0; z-index: 72; width: min(300px, calc(100vw - 44px)); border-radius: 0; transform: translateX(-100%); transition: transform .18s ease; }
  .conversation-sidebar.mobile-open { transform: translateX(0); }
  .mobile-close-button { width: 30px; height: 30px; display: grid; place-items: center; border: 0; border-radius: 5px; color: var(--muted); background: transparent; }
  .history-backdrop { position: fixed; inset: 0; z-index: 70; display: block; border: 0; background: rgba(15,24,22,.5); }
  .chat-panel { height: 100%; }
  .conversation-delete { opacity: 1; }
}
@media (max-width: 700px) {
  .chat-heading { min-height: 72px; align-items: center; flex-direction: row; gap: 8px; margin-bottom: 10px; padding: 12px 14px; border-radius: 18px; }
  .chat-heading > div:first-child p, .chat-heading > div:first-child > span, .knowledge-status { display: none; }
  .chat-heading h1 { margin: 2px 0; font-size: 18px; line-height: 30px; }
  .chat-heading-actions { margin-left: auto; }
  .message-area { min-height: 0; padding: 12px; }
  .message-row { gap: 8px; margin-bottom: 20px; }
  .avatar { flex-basis: 28px; height: 28px; }
  .message-body { max-width: calc(100% - 47px); }
  .bubble { padding: 11px 12px; }
  .composer { width: calc(100% - 20px); }
  .composer textarea { min-height: 22px; }
  .medical-note { margin-bottom: 7px; }
}
</style>
