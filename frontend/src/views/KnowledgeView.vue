<script setup>
import { computed, onMounted, ref } from 'vue'
import { AlertTriangle, Database, FileText, Layers3, RefreshCw, Trash2, UploadCloud, X } from '@lucide/vue'

import { deleteDocument, getDocuments, uploadDocument } from '../api/documents'
import { getApiErrorMessage } from '../api/http'

const MAX_FILE_SIZE = 10 * 1024 * 1024
const ALLOWED_SUFFIXES = ['.pdf', '.txt']

const documents = ref([])
const listLoading = ref(false)
const selectedFile = ref(null)
const fileInput = ref(null)
const dragActive = ref(false)
const uploading = ref(false)
const uploadProgress = ref(0)
const deleting = ref(false)
const deleteTarget = ref(null)
const errorMessage = ref('')
const successMessage = ref('')

const totalChunks = computed(() =>
  documents.value.reduce((total, document) => total + document.chunk_count, 0),
)

async function loadDocuments() {
  listLoading.value = true
  errorMessage.value = ''
  try {
    const data = await getDocuments()
    documents.value = data.documents || []
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    listLoading.value = false
  }
}

function validateAndSelect(file) {
  errorMessage.value = ''
  successMessage.value = ''
  if (!file) return

  const lowerName = file.name.toLowerCase()
  if (!ALLOWED_SUFFIXES.some((suffix) => lowerName.endsWith(suffix))) {
    errorMessage.value = '只支持 PDF 和 TXT 文件。'
    return
  }
  if (file.size > MAX_FILE_SIZE) {
    errorMessage.value = '文件大小不能超过 10 MB。'
    return
  }
  selectedFile.value = file
}

function handleFileInput(event) {
  validateAndSelect(event.target.files?.[0])
}

function handleDrop(event) {
  dragActive.value = false
  validateAndSelect(event.dataTransfer.files?.[0])
}

function clearSelectedFile() {
  selectedFile.value = null
  if (fileInput.value) fileInput.value.value = ''
}

async function startUpload() {
  if (!selectedFile.value || uploading.value) return
  uploading.value = true
  uploadProgress.value = 0
  errorMessage.value = ''
  successMessage.value = ''

  try {
    const result = await uploadDocument(selectedFile.value, (progress) => {
      uploadProgress.value = progress
    })
    uploadProgress.value = 100
    successMessage.value = `${result.file_name} 已提交，等待管理员审核。`
    clearSelectedFile()
    await loadDocuments()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    uploading.value = false
  }
}

function requestDelete(document) {
  if (!document.can_delete) return
  deleteTarget.value = document
  errorMessage.value = ''
}

async function confirmDelete() {
  if (!deleteTarget.value || deleting.value) return
  deleting.value = true
  errorMessage.value = ''
  successMessage.value = ''
  const target = deleteTarget.value

  try {
    await deleteDocument(target.document_id)
    deleteTarget.value = null
    successMessage.value = `${target.file_name} 已从知识库中删除。`
    await loadDocuments()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    deleting.value = false
  }
}

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatDate(value) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

onMounted(loadDocuments)
</script>

<template>
  <section class="knowledge-page">
    <header class="page-heading">
      <div>
        <span>KNOWLEDGE BASE</span>
        <h1>知识库管理</h1>
        <p>提交医疗资料供管理员审核，审核通过后才会进入公共知识库。</p>
      </div>
      <div class="summary-cards">
        <div><Database :size="17" /><span><strong>{{ documents.length }}</strong><small>已发布文档</small></span></div>
        <div><Layers3 :size="17" /><span><strong>{{ totalChunks }}</strong><small>知识片段</small></span></div>
      </div>
    </header>

    <div v-if="errorMessage" class="notice error" role="alert">
        <span>{{ errorMessage }}</span><button aria-label="关闭错误提示" @click="errorMessage = ''"><X :size="15" /></button>
    </div>
    <div v-if="successMessage" class="notice success" role="status">
        <span>{{ successMessage }}</span><button aria-label="关闭成功提示" @click="successMessage = ''"><X :size="15" /></button>
    </div>

    <section class="upload-card">
      <div class="section-title">
        <div><UploadCloud :size="18" /><h2>提交新资料</h2></div>
        <small>PDF / TXT · 最大 10 MB</small>
      </div>

      <input ref="fileInput" type="file" accept=".pdf,.txt" hidden @change="handleFileInput" />
      <div
        class="drop-zone"
        :class="{ active: dragActive }"
        role="button"
        tabindex="0"
        @click="fileInput?.click()"
        @keydown.enter="fileInput?.click()"
        @dragenter.prevent="dragActive = true"
        @dragover.prevent="dragActive = true"
        @dragleave.prevent="dragActive = false"
        @drop.prevent="handleDrop"
      >
        <div class="upload-symbol"><UploadCloud :size="21" /></div>
        <strong>点击选择或拖放文件到这里</strong>
        <p>系统会先校验并生成解析预览，提交阶段不会调用向量模型。</p>
      </div>

      <div v-if="selectedFile" class="selected-file">
        <div class="file-badge"><FileText :size="17" /></div>
        <div><strong>{{ selectedFile.name }}</strong><small>{{ formatFileSize(selectedFile.size) }}</small></div>
        <button v-if="!uploading" aria-label="移除已选文件" @click="clearSelectedFile"><X :size="17" /></button>
      </div>

      <div v-if="uploading" class="progress-area">
        <div><span>正在上传并提交审核</span><strong>{{ uploadProgress }}%</strong></div>
        <div class="progress-track"><i :style="{ width: `${uploadProgress}%` }"></i></div>
        <p>当前阶段只上传原文件并生成审核预览，不会调用向量模型。</p>
      </div>

      <div class="upload-actions">
        <span>提交成功表示进入审核队列，并不表示已经发布。</span>
        <el-button class="upload-button" type="primary" round :loading="uploading" :disabled="!selectedFile" @click="startUpload">
          提交审核
        </el-button>
      </div>
    </section>

    <section class="document-card">
      <div class="section-title">
        <div><Database :size="18" /><h2>公共知识库</h2></div>
        <el-button plain round :loading="listLoading" @click="loadDocuments"><RefreshCw :size="14" />刷新列表</el-button>
      </div>

      <div v-if="listLoading && !documents.length" class="loading-state">正在读取知识库…</div>
      <div v-else-if="!documents.length" class="empty-state">
        <div>空</div><strong>知识库中还没有上传文档</strong><p>上传第一份 PDF 或 TXT 后，文档会显示在这里。</p>
      </div>
      <div v-else class="document-list">
        <div class="table-head"><span>文档</span><span>大小</span><span>片段</span><span>上传时间</span><span>操作</span></div>
        <article v-for="document in documents" :key="document.document_id" class="document-row">
          <div class="document-name">
            <span class="type-badge"><FileText :size="16" /></span>
            <div><strong>{{ document.file_name }}</strong><small>{{ document.status === 'ready' ? '已入库' : document.status }}</small></div>
          </div>
          <span data-label="大小">{{ formatFileSize(document.file_size) }}</span>
          <span data-label="片段">{{ document.chunk_count }}</span>
          <span data-label="上传时间">{{ formatDate(document.created_at) }}</span>
          <button v-if="document.can_delete" class="delete-button" title="删除文档" aria-label="删除文档" @click="requestDelete(document)"><Trash2 :size="15" /></button>
          <span v-else class="protected-label" data-label="权限" :title="document.is_system ? '系统预置资料不可删除' : '只有上传者可以删除'">
            {{ document.is_system ? '系统资料' : '仅上传者可删' }}
          </span>
        </article>
      </div>
    </section>

    <div v-if="deleteTarget" class="dialog-backdrop" @click.self="deleteTarget = null">
      <div class="delete-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-title">
        <div class="warning-mark"><AlertTriangle :size="20" /></div>
        <h2 id="delete-title">确认删除文档？</h2>
        <p>“{{ deleteTarget.file_name }}”的原文件、登记记录和全部向量片段都会被删除，此操作无法撤销。</p>
        <div>
          <el-button round :disabled="deleting" @click="deleteTarget = null">取消</el-button>
          <el-button type="danger" round :loading="deleting" @click="confirmDelete">确认删除</el-button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.knowledge-page { padding: 0 0 24px; }
.summary-cards { display: flex; gap: 10px; }
.summary-cards div { min-width: 126px; display: flex; align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 7px; background: var(--bg-surface); }
.summary-cards svg { color: var(--brand); }
.summary-cards strong, .summary-cards small { display: block; }
.summary-cards strong { color: var(--text-strong); font-size: 18px; }
.summary-cards small { margin-top: 2px; color: var(--muted); font-size: 11px; }
.notice { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 12px; padding: 10px 12px; border: 1px solid transparent; border-radius: 6px; font-size: 12px; }
.notice.error { color: #982e2a; border-color: #efc3bf; background: #fff8f7; }
.notice.success { color: #176a4d; border-color: #badcca; background: #f4fbf7; }
.notice button { display: grid; place-items: center; padding: 2px; border: 0; color: inherit; background: transparent; cursor: pointer; }
.upload-card, .document-card { padding: 18px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg-surface); }
.document-card { margin-top: 16px; }
.section-title { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 15px; }
.section-title > div { display: flex; align-items: center; gap: 8px; }
.section-title > div > svg { color: var(--brand); }
.section-title h2 { margin: 0; color: var(--text-strong); font-size: 15px; }
.section-title small { color: var(--muted); font-size: 12px; }
.drop-zone { padding: 28px 20px; border: 1px dashed #b9cec8; border-radius: 7px; text-align: center; background: var(--bg-subtle); cursor: pointer; transition: border-color .16s ease, background .16s ease; }
.drop-zone:hover, .drop-zone.active { border-color: var(--primary); background: #f0f8f5; }
.upload-symbol { width: 38px; height: 38px; display: grid; place-items: center; margin: 0 auto 11px; border-radius: 7px; color: var(--brand); background: #e5f2ee; }
.drop-zone strong { display: block; font-size: 15px; }
.drop-zone p { margin: 8px 0 0; color: var(--muted); font-size: 12px; }
.selected-file { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 11px; margin-top: 12px; padding: 11px; border: 1px solid var(--line); border-radius: 7px; }
.file-badge, .type-badge { display: grid; place-items: center; color: var(--primary-dark); background: #e4f2ed; font-size: 10px; font-weight: 800; }
.file-badge { width: 36px; height: 36px; border-radius: 6px; }
.selected-file strong, .selected-file small { display: block; }
.selected-file small { margin-top: 3px; color: var(--muted); font-size: 11px; }
.selected-file button { border: 0; color: var(--muted); background: transparent; font-size: 22px; cursor: pointer; }
.progress-area { margin-top: 14px; }
.progress-area > div:first-child { display: flex; justify-content: space-between; font-size: 12px; }
.progress-track { height: 6px; margin-top: 8px; overflow: hidden; border-radius: 3px; background: #e8efed; }
.progress-track i { display: block; height: 100%; border-radius: inherit; background: var(--primary); transition: width .2s; }
.progress-area p { margin: 7px 0 0; color: var(--muted); font-size: 11px; }
.upload-actions { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-top: 16px; }
.upload-actions > span { color: var(--muted); font-size: 12px; }
.table-head, .document-row { display: grid; grid-template-columns: minmax(240px, 2fr) .65fr .55fr 1fr .5fr; align-items: center; gap: 16px; }
.table-head { padding: 10px 14px; color: var(--muted); border-bottom: 1px solid var(--line); font-size: 11px; }
.document-row { padding: 15px 14px; border-bottom: 1px solid #edf2f0; color: var(--muted); font-size: 13px; }
.document-row:last-child { border-bottom: 0; }
.document-name { display: flex; align-items: center; gap: 11px; min-width: 0; }
.type-badge { flex: 0 0 32px; height: 32px; border-radius: 6px; }
.document-name div { min-width: 0; }
.document-name strong, .document-name small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.document-name strong { color: var(--ink); font-size: 13px; }
.document-name small { margin-top: 3px; color: #18a875; font-size: 10px; }
.delete-button { width: 30px; height: 30px; display: grid; place-items: center; padding: 0; border: 1px solid transparent; border-radius: 6px; color: var(--danger); background: transparent; cursor: pointer; }
.delete-button:hover { border-color: #efc3bf; background: #fff8f7; }
.protected-label { width: fit-content; color: #7f918d; font-size: 11px; white-space: nowrap; }
.loading-state, .empty-state { padding: 48px 20px; color: var(--muted); text-align: center; }
.empty-state div { width: 40px; height: 40px; display: grid; place-items: center; margin: 0 auto 13px; border-radius: 7px; background: #edf3f1; }
.empty-state strong { color: var(--ink); }
.empty-state p { margin: 7px 0 0; font-size: 12px; }
.dialog-backdrop { position: fixed; inset: 0; z-index: 100; display: grid; place-items: center; padding: 20px; background: rgba(12,18,17,.52); }
.delete-dialog { width: min(420px, 100%); padding: 22px; border: 1px solid var(--border-default); border-radius: 8px; background: white; box-shadow: 0 22px 60px rgba(12,18,17,.24); text-align: left; }
.warning-mark { width: 38px; height: 38px; display: grid; place-items: center; margin: 0 0 15px; border-radius: 7px; color: var(--danger); background: #fff0ef; }
.delete-dialog h2 { margin: 0; font-size: 20px; }
.delete-dialog p { margin: 12px 0 22px; color: var(--muted); font-size: 13px; line-height: 1.7; }
.delete-dialog > div:last-child { display: flex; justify-content: flex-end; gap: 8px; }
@media (max-width: 780px) {
  .knowledge-page { padding-top: 28px; }
  .page-heading { align-items: start; flex-direction: column; }
  .summary-cards { width: 100%; }
  .summary-cards div { flex: 1; }
  .table-head { display: none; }
  .document-row { grid-template-columns: 1fr auto; gap: 9px 12px; padding-block: 18px; }
  .document-name { grid-column: 1 / -1; }
  .document-row > span::before { content: attr(data-label) '：'; color: #9aaba7; }
  .document-row > span:nth-of-type(3) { grid-column: 1 / -1; }
  .delete-button { grid-column: 2; grid-row: 2 / span 2; align-self: center; }
  .protected-label { grid-column: 1 / -1; }
  .upload-actions { align-items: stretch; flex-direction: column; }
  .upload-actions .el-button { width: 100%; }
}
</style>
