<script setup>
import { computed, onMounted, ref } from 'vue'

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
    successMessage.value = `${result.file_name} 已成功入库，共 ${result.chunk_count} 个片段。`
    clearSelectedFile()
    await loadDocuments()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    uploading.value = false
  }
}

function requestDelete(document) {
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
        <p>上传医疗资料，系统会自动解析、切分并写入本地向量库。</p>
      </div>
      <div class="summary-cards">
        <div><strong>{{ documents.length }}</strong><small>已上传文档</small></div>
        <div><strong>{{ totalChunks }}</strong><small>知识片段</small></div>
      </div>
    </header>

    <div v-if="errorMessage" class="notice error" role="alert">
      <span>{{ errorMessage }}</span><button @click="errorMessage = ''">关闭</button>
    </div>
    <div v-if="successMessage" class="notice success" role="status">
      <span>{{ successMessage }}</span><button @click="successMessage = ''">关闭</button>
    </div>

    <section class="upload-card">
      <div class="section-title">
        <div><span>01</span><h2>上传新资料</h2></div>
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
        <div class="upload-symbol">↑</div>
        <strong>点击选择或拖放文件到这里</strong>
        <p>系统会根据文件内容计算 SHA-256，避免重复向量化和重复计费。</p>
      </div>

      <div v-if="selectedFile" class="selected-file">
        <div class="file-badge">{{ selectedFile.name.toLowerCase().endsWith('.pdf') ? 'PDF' : 'TXT' }}</div>
        <div><strong>{{ selectedFile.name }}</strong><small>{{ formatFileSize(selectedFile.size) }}</small></div>
        <button v-if="!uploading" aria-label="移除已选文件" @click="clearSelectedFile">×</button>
      </div>

      <div v-if="uploading" class="progress-area">
        <div><span>正在上传并向量化</span><strong>{{ uploadProgress }}%</strong></div>
        <div class="progress-track"><i :style="{ width: `${uploadProgress}%` }"></i></div>
        <p>向量化阶段可能需要一些时间，请不要重复提交。</p>
      </div>

      <div class="upload-actions">
        <span>上传成功后即可在“知识问答”页面检索内容。</span>
        <el-button type="primary" round :loading="uploading" :disabled="!selectedFile" @click="startUpload">
          开始入库
        </el-button>
      </div>
    </section>

    <section class="document-card">
      <div class="section-title">
        <div><span>02</span><h2>已上传文档</h2></div>
        <el-button plain round :loading="listLoading" @click="loadDocuments">刷新列表</el-button>
      </div>

      <div v-if="listLoading && !documents.length" class="loading-state">正在读取知识库…</div>
      <div v-else-if="!documents.length" class="empty-state">
        <div>空</div><strong>知识库中还没有上传文档</strong><p>上传第一份 PDF 或 TXT 后，文档会显示在这里。</p>
      </div>
      <div v-else class="document-list">
        <div class="table-head"><span>文档</span><span>大小</span><span>片段</span><span>上传时间</span><span>操作</span></div>
        <article v-for="document in documents" :key="document.document_id" class="document-row">
          <div class="document-name">
            <span class="type-badge">{{ document.file_name.toLowerCase().endsWith('.pdf') ? 'PDF' : 'TXT' }}</span>
            <div><strong>{{ document.file_name }}</strong><small>{{ document.status === 'ready' ? '已入库' : document.status }}</small></div>
          </div>
          <span data-label="大小">{{ formatFileSize(document.file_size) }}</span>
          <span data-label="片段">{{ document.chunk_count }}</span>
          <span data-label="上传时间">{{ formatDate(document.created_at) }}</span>
          <button class="delete-button" @click="requestDelete(document)">删除</button>
        </article>
      </div>
    </section>

    <div v-if="deleteTarget" class="dialog-backdrop" @click.self="deleteTarget = null">
      <div class="delete-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-title">
        <div class="warning-mark">!</div>
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
.knowledge-page { padding: 48px 0 64px; }
.page-heading { display: flex; align-items: end; justify-content: space-between; gap: 24px; margin-bottom: 24px; }
.page-heading > div > span, .section-title > div > span { color: var(--primary); font-size: 11px; font-weight: 800; letter-spacing: .16em; }
.page-heading h1 { margin: 8px 0 6px; font-size: 34px; letter-spacing: -.04em; }
.page-heading p { margin: 0; color: var(--muted); font-size: 14px; }
.summary-cards { display: flex; gap: 10px; }
.summary-cards div { min-width: 112px; padding: 13px 16px; border: 1px solid var(--line); border-radius: 14px; background: rgba(255,255,255,.72); }
.summary-cards strong, .summary-cards small { display: block; }
.summary-cards strong { font-size: 22px; }
.summary-cards small { margin-top: 2px; color: var(--muted); font-size: 11px; }
.notice { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 14px; padding: 12px 15px; border-radius: 11px; font-size: 13px; }
.notice.error { color: #a33f2f; background: #fff0ed; }
.notice.success { color: #126e54; background: #e6f6ef; }
.notice button { border: 0; color: inherit; background: transparent; cursor: pointer; }
.upload-card, .document-card { padding: 24px; border: 1px solid var(--line); border-radius: 20px; background: rgba(255,255,255,.9); box-shadow: 0 20px 50px rgba(35,87,77,.06); }
.document-card { margin-top: 20px; }
.section-title { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.section-title > div { display: flex; align-items: baseline; gap: 10px; }
.section-title h2 { margin: 0; font-size: 18px; }
.section-title small { color: var(--muted); font-size: 12px; }
.drop-zone { padding: 34px 20px; border: 1.5px dashed #b9cec8; border-radius: 16px; text-align: center; background: #f8fbfa; cursor: pointer; transition: .2s ease; }
.drop-zone:hover, .drop-zone.active { border-color: var(--primary); background: #eff8f5; transform: translateY(-1px); }
.upload-symbol { width: 42px; height: 42px; display: grid; place-items: center; margin: 0 auto 13px; border-radius: 13px; color: white; background: var(--primary); font-size: 22px; }
.drop-zone strong { display: block; font-size: 15px; }
.drop-zone p { margin: 8px 0 0; color: var(--muted); font-size: 12px; }
.selected-file { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 13px; margin-top: 14px; padding: 13px; border: 1px solid var(--line); border-radius: 13px; }
.file-badge, .type-badge { display: grid; place-items: center; color: var(--primary-dark); background: #e4f2ed; font-size: 10px; font-weight: 800; }
.file-badge { width: 42px; height: 42px; border-radius: 10px; }
.selected-file strong, .selected-file small { display: block; }
.selected-file small { margin-top: 3px; color: var(--muted); font-size: 11px; }
.selected-file button { border: 0; color: var(--muted); background: transparent; font-size: 22px; cursor: pointer; }
.progress-area { margin-top: 14px; }
.progress-area > div:first-child { display: flex; justify-content: space-between; font-size: 12px; }
.progress-track { height: 7px; margin-top: 8px; overflow: hidden; border-radius: 10px; background: #e8efed; }
.progress-track i { display: block; height: 100%; border-radius: inherit; background: var(--primary); transition: width .2s; }
.progress-area p { margin: 7px 0 0; color: var(--muted); font-size: 11px; }
.upload-actions { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-top: 16px; }
.upload-actions > span { color: var(--muted); font-size: 12px; }
.table-head, .document-row { display: grid; grid-template-columns: minmax(240px, 2fr) .65fr .55fr 1fr .5fr; align-items: center; gap: 16px; }
.table-head { padding: 10px 14px; color: var(--muted); border-bottom: 1px solid var(--line); font-size: 11px; }
.document-row { padding: 15px 14px; border-bottom: 1px solid #edf2f0; color: var(--muted); font-size: 13px; }
.document-row:last-child { border-bottom: 0; }
.document-name { display: flex; align-items: center; gap: 11px; min-width: 0; }
.type-badge { flex: 0 0 36px; height: 36px; border-radius: 9px; }
.document-name div { min-width: 0; }
.document-name strong, .document-name small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.document-name strong { color: var(--ink); font-size: 13px; }
.document-name small { margin-top: 3px; color: #18a875; font-size: 10px; }
.delete-button { width: fit-content; padding: 5px 10px; border: 0; border-radius: 7px; color: #bd4b39; background: #fff0ed; cursor: pointer; }
.loading-state, .empty-state { padding: 48px 20px; color: var(--muted); text-align: center; }
.empty-state div { width: 46px; height: 46px; display: grid; place-items: center; margin: 0 auto 13px; border-radius: 14px; background: #edf3f1; }
.empty-state strong { color: var(--ink); }
.empty-state p { margin: 7px 0 0; font-size: 12px; }
.dialog-backdrop { position: fixed; inset: 0; z-index: 20; display: grid; place-items: center; padding: 20px; background: rgba(18,39,34,.45); backdrop-filter: blur(4px); }
.delete-dialog { width: min(420px, 100%); padding: 28px; border-radius: 20px; background: white; box-shadow: 0 24px 80px rgba(0,0,0,.2); text-align: center; }
.warning-mark { width: 44px; height: 44px; display: grid; place-items: center; margin: 0 auto 14px; border-radius: 50%; color: #bd4b39; background: #fff0ed; font-size: 22px; font-weight: 800; }
.delete-dialog h2 { margin: 0; font-size: 20px; }
.delete-dialog p { margin: 12px 0 22px; color: var(--muted); font-size: 13px; line-height: 1.7; }
.delete-dialog > div:last-child { display: flex; justify-content: center; gap: 10px; }
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
  .upload-actions { align-items: stretch; flex-direction: column; }
  .upload-actions .el-button { width: 100%; }
}
</style>
