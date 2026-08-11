<script setup>
import { computed, nextTick, ref } from 'vue'
import { ImagePlus } from '@lucide/vue'
import ModelSelector from '../../components/ModelSelector.vue'
import { useAgentDraftRegistry } from './useAgentDraftRegistry.js'
import AttachmentDraftTray from '../attachments/AttachmentDraftTray.vue'

const props = defineProps({
  draftKey: { type: String, required: true },
  sendDisabled: Boolean,
  running: Boolean,
  references: { type: Array, default: () => [] },
})
const emit = defineEmits(['send', 'stop', 'remove-reference'])
const textarea = ref(null)
const imageInput = ref(null)
const draftRegistry = useAgentDraftRegistry()
const currentDraft = computed(() => draftRegistry.draftFor(props.draftKey))
const value = computed({
  get: () => currentDraft.value.state.content,
  set: (content) => { currentDraft.value.state.content = content },
})
const draftItems = computed(() => currentDraft.value.attachments.items.value)
const attachmentError = computed(() => currentDraft.value.attachments.error.value)
const uploadingAttachments = computed(() => currentDraft.value.attachments.uploading.value)
const modelId = ref('qwen')
const awaitingAcceptance = computed(() => (
  currentDraft.value.state.phase === 'awaiting_acceptance'
  || currentDraft.value.state.phase === 'uploading'
))
const canSend = computed(() => (
  (value.value.trim() || currentDraft.value.attachments.hasAttachments.value)
  && !props.sendDisabled && !awaitingAcceptance.value
))

function focus() {
  resizeTextarea()
  if (!awaitingAcceptance.value) textarea.value?.focus()
}

defineExpose({ focus })

async function submit() {
  const content = value.value.trim()
  if ((!content && !currentDraft.value.attachments.hasAttachments.value) || !canSend.value) return
  try {
    const submission = await draftRegistry.prepareSubmission(props.draftKey)
    emit('send', { ...submission, modelId: modelId.value })
  } catch {
    // 失败状态和可重试提示由共享草稿状态机维护。
  }
}

function chooseImages() { imageInput.value?.click() }
function handleImageSelection(event) {
  currentDraft.value.attachments.addFiles(event.target.files)
  event.target.value = ''
}
function retryUpload(item) { currentDraft.value.attachments.upload(item).catch(() => {}) }
function removeImage(item) { currentDraft.value.attachments.remove(item) }
function handlePaste(event) { currentDraft.value.attachments.handlePaste(event) }

function resizeTextarea() {
  const input = textarea.value
  if (!input) return
  input.style.height = 'auto'
  const lineHeight = Number.parseFloat(window.getComputedStyle(input).lineHeight) || 22
  const maxHeight = lineHeight * 4
  const nextHeight = Math.min(input.scrollHeight, maxHeight)
  input.style.height = `${Math.max(lineHeight, nextHeight)}px`
  input.style.overflowY = input.scrollHeight > maxHeight ? 'auto' : 'hidden'
}

function handleKeydown(event) {
  if (event.key !== 'Enter' || event.shiftKey) return
  event.preventDefault()
  submit()
}
</script>

<template>
  <form class="composer" @submit.prevent="submit">
    <label for="agent-message">给 Agent 发送任务</label>
    <div v-if="references.length" class="references" aria-label="本轮显式引用">
      <button
        v-for="item in references"
        :key="item.key"
        type="button"
        :aria-label="`移除引用 ${item.label}`"
        @click="$emit('remove-reference', item)"
      >
        @ {{ item.label }} ×
      </button>
    </div>
    <AttachmentDraftTray :items="draftItems" @remove="removeImage" @retry="retryUpload" />
    <textarea
      ref="textarea"
      id="agent-message"
      v-model="value"
      maxlength="4000"
      rows="1"
      placeholder="输入任务，Enter 发送，Shift + Enter 换行"
      :disabled="awaitingAcceptance"
      @input="resizeTextarea"
      @keydown="handleKeydown"
      @paste="handlePaste"
    />
    <div class="composer-footer">
      <div class="composer-tools">
        <input ref="imageInput" type="file" accept="image/jpeg,image/png,image/webp" multiple hidden @change="handleImageSelection" />
        <button type="button" class="add-image-button" aria-label="添加图片" :disabled="awaitingAcceptance || draftItems.length >= 3" @click="chooseImages"><ImagePlus :size="17" /><span>添加图片</span></button>
      </div>
      <div class="composer-actions">
        <ModelSelector v-model="modelId" surface="agent" />
        <small v-if="value.length">{{ value.length }} / 4000</small>
        <el-button v-if="running" type="danger" plain round @click="$emit('stop')">停止生成</el-button>
        <el-button v-else type="primary" round native-type="submit" :loading="uploadingAttachments" :disabled="!canSend">
          发送任务
        </el-button>
      </div>
    </div>
    <p v-if="attachmentError" class="attachment-error" role="alert">{{ attachmentError }}</p>
  </form>
</template>

<style scoped>
.composer {
  position: relative;
  z-index: 4;
  width: min(calc(100% - 36px), 960px);
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 9px;
  margin: 0 auto 8px;
  padding: 10px 12px;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 8px 24px rgba(23, 32, 30, .08);
}
.composer label {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
}
.references {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 7px;
}
.references button {
  max-width: 190px;
  overflow: hidden;
  padding: 4px 8px;
  border: 1px solid #cbdad3;
  border-radius: 999px;
  color: #226347;
  background: #edf6f2;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}
.composer textarea {
  width: 100%;
  min-height: 22px;
  max-height: 88px;
  align-self: center;
  resize: none;
  overflow-y: hidden;
  border: 0;
  outline: 0;
  box-sizing: border-box;
  color: var(--ink);
  background: transparent;
  font: inherit;
  font-size: 13px;
  line-height: 22px;
}
.composer textarea::placeholder { color: #9aaba7; }
.composer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin: 0;
}
.composer-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; }
.composer small { color: var(--muted); }
.composer-tools { display: flex; align-items: center; }
.add-image-button { min-height: 40px; display: inline-flex; align-items: center; gap: 7px; padding: 0 10px; border: 0; border-radius: 11px; color: var(--ui-text-body); background: transparent; cursor: pointer; }
.add-image-button:hover { color: var(--ui-brand-blue); background: rgba(235,240,255,.72); }
.add-image-button:disabled { cursor: not-allowed; opacity: .45; }
.attachment-error { margin: -2px 2px 0; color: var(--ui-danger); font-size: 11px; }
@media (max-width: 760px) {
  .composer { width: calc(100% - 20px); margin-bottom: 8px; }
  .add-image-button { width: 44px; justify-content: center; padding: 0; }
  .add-image-button span { display: none; }
}
</style>
