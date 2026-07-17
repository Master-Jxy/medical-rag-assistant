<script setup>
import { computed, onMounted, ref } from 'vue'

import {
  createSystemDocument,
  deleteSystemDocument,
  replaceSystemDocument,
} from '../api/adminDocuments.js'
import { getDocuments } from '../api/documents.js'
import { getApiErrorMessage } from '../api/http.js'

const documents = ref([])
const loading = ref(false)
const creating = ref(false)
const activeDocumentId = ref('')
const selectedFile = ref(null)
const errorMessage = ref('')
const successMessage = ref('')

const systemDocuments = computed(() => documents.value.filter((item) => item.is_system))

async function loadDocuments() {
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await getDocuments()
    documents.value = result.documents || []
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    loading.value = false
  }
}

function validateFile(file) {
  if (!file) return false
  const validType = ['.pdf', '.txt'].some((suffix) => file.name.toLowerCase().endsWith(suffix))
  if (!validType || file.size > 10 * 1024 * 1024) {
    errorMessage.value = '请选择不超过 10 MB 的 PDF 或 TXT 文件。'
    return false
  }
  return true
}

function selectCreateFile(event) {
  const file = event.target.files?.[0]
  if (validateFile(file)) selectedFile.value = file
}

async function createDocument() {
  if (!selectedFile.value || creating.value) return
  creating.value = true
  errorMessage.value = ''
  try {
    const result = await createSystemDocument(selectedFile.value)
    successMessage.value = `${result.file_name} 已作为系统资料入库。`
    selectedFile.value = null
    await loadDocuments()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    creating.value = false
  }
}

async function replaceDocument(document, event) {
  const file = event.target.files?.[0]
  if (!validateFile(file) || activeDocumentId.value) return
  activeDocumentId.value = document.document_id
  errorMessage.value = ''
  try {
    const result = await replaceSystemDocument(document.document_id, file)
    successMessage.value = `${document.file_name} 已整体替换为 ${result.file_name}。`
    await loadDocuments()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    activeDocumentId.value = ''
    event.target.value = ''
  }
}

async function removeDocument(document) {
  if (activeDocumentId.value) return
  if (!window.confirm(`确定删除系统资料“${document.file_name}”吗？`)) return
  activeDocumentId.value = document.document_id
  errorMessage.value = ''
  try {
    await deleteSystemDocument(document.document_id)
    successMessage.value = `${document.file_name} 已删除。`
    await loadDocuments()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    activeDocumentId.value = ''
  }
}

onMounted(loadDocuments)
</script>

<template>
  <section class="admin-page">
    <header>
      <div><span>ADMIN CONSOLE</span><h1>系统知识库管理</h1></div>
      <p>创建、整体替换或删除系统公共资料。普通用户上传的资料不在这里操作。</p>
    </header>

    <div v-if="errorMessage" class="notice error" role="alert">{{ errorMessage }}</div>
    <div v-if="successMessage" class="notice success" role="status">{{ successMessage }}</div>

    <section class="admin-card create-card">
      <div><h2>新增系统资料</h2><p>内容哈希相同的文件会被跳过，避免重复向量化。</p></div>
      <label class="file-picker">
        <input type="file" accept=".pdf,.txt" @change="selectCreateFile" />
        <span>{{ selectedFile?.name || '选择 PDF / TXT' }}</span>
      </label>
      <button :disabled="!selectedFile || creating" @click="createDocument">
        {{ creating ? '正在入库…' : '确认入库' }}
      </button>
    </section>

    <section class="admin-card">
      <div class="list-heading">
        <div><h2>系统资料</h2><p>共 {{ systemDocuments.length }} 份</p></div>
        <button :disabled="loading" @click="loadDocuments">刷新</button>
      </div>
      <p v-if="loading && !systemDocuments.length" class="empty">正在读取…</p>
      <p v-else-if="!systemDocuments.length" class="empty">暂无系统资料</p>
      <article v-for="document in systemDocuments" :key="document.document_id" class="document-row">
        <div><strong>{{ document.file_name }}</strong><small>{{ document.chunk_count }} 个知识片段</small></div>
        <div class="row-actions">
          <label class="replace-button">
            <input
              class="replace-input"
              type="file"
              accept=".pdf,.txt"
              :disabled="Boolean(activeDocumentId)"
              @change="replaceDocument(document, $event)"
            />
            <span>{{ activeDocumentId === document.document_id ? '处理中…' : '整体替换' }}</span>
          </label>
          <button class="delete-button" :disabled="Boolean(activeDocumentId)" @click="removeDocument(document)">删除</button>
        </div>
      </article>
    </section>
  </section>
</template>

<style scoped>
.admin-page { padding: 48px 0 64px; }
header { display: flex; align-items: end; justify-content: space-between; gap: 24px; margin-bottom: 24px; }
header span { color: var(--primary); font-size: 11px; font-weight: 800; letter-spacing: .16em; }
header h1 { margin: 8px 0 0; font-size: 34px; }
header p, .admin-card p { color: var(--muted); font-size: 13px; }
.notice { margin-bottom: 14px; padding: 12px 15px; border-radius: 11px; font-size: 13px; }
.notice.error { color: #a33f2f; background: #fff0ed; }
.notice.success { color: #126e54; background: #e6f6ef; }
.admin-card { padding: 24px; border: 1px solid var(--line); border-radius: 20px; background: rgba(255,255,255,.9); }
.admin-card + .admin-card { margin-top: 20px; }
.admin-card h2 { margin: 0; font-size: 18px; }
.admin-card p { margin: 6px 0 0; }
.create-card { display: grid; grid-template-columns: 1fr minmax(220px, .6fr) auto; align-items: center; gap: 18px; }
.file-picker, .replace-button { position: relative; overflow: hidden; cursor: pointer; }
.file-picker input, .replace-button input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.file-picker span, .replace-button span, button { display: inline-block; padding: 9px 15px; border: 1px solid var(--line); border-radius: 10px; background: white; font-size: 13px; cursor: pointer; }
.file-picker span { width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.create-card > button { color: white; border-color: var(--primary); background: var(--primary); }
button:disabled { opacity: .55; cursor: not-allowed; }
.list-heading, .document-row, .row-actions { display: flex; align-items: center; }
.list-heading, .document-row { justify-content: space-between; gap: 18px; }
.document-row { padding: 16px 4px; border-top: 1px solid #edf2f0; }
.document-row strong, .document-row small { display: block; }
.document-row small { margin-top: 4px; color: var(--muted); font-size: 11px; }
.row-actions { gap: 8px; }
.delete-button { color: #bd4b39; background: #fff0ed; }
.empty { padding: 36px 0; text-align: center; }
@media (max-width: 760px) {
  header, .create-card, .document-row { align-items: stretch; flex-direction: column; }
  .create-card { display: flex; }
  .row-actions { justify-content: flex-end; }
}
</style>
