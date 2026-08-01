<script setup>
import { computed, onMounted, ref } from 'vue'
import { Database, FileText, RefreshCw, Replace, Trash2, UploadCloud } from '@lucide/vue'

import ConfirmDialog from '../components/ConfirmDialog.vue'
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
const deleteTarget = ref(null)
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

async function removeDocument() {
  if (activeDocumentId.value || !deleteTarget.value) return
  const document = deleteTarget.value
  activeDocumentId.value = document.document_id
  errorMessage.value = ''
  try {
    await deleteSystemDocument(document.document_id)
    deleteTarget.value = null
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
  <section class="platform-page admin-page">
    <header class="page-toolbar"><div><span>SYSTEM KNOWLEDGE</span><h1>系统资料</h1><p>创建、整体替换或删除管理员维护的公共资料。</p></div><button class="secondary-action" type="button" :disabled="loading" @click="loadDocuments"><RefreshCw :size="15" />刷新</button></header>

    <div v-if="errorMessage" class="notice error" role="alert">{{ errorMessage }}</div>
    <div v-if="successMessage" class="notice success" role="status">{{ successMessage }}</div>

    <section class="admin-card create-card">
      <span class="create-icon"><UploadCloud :size="19" /></span>
      <div><h2>新增系统资料</h2><p>支持 PDF / TXT，最大 10 MB；相同内容会自动去重。</p></div>
      <label class="file-picker">
        <input type="file" accept=".pdf,.txt" @change="selectCreateFile" />
        <span><FileText :size="14" />{{ selectedFile?.name || '选择 PDF / TXT' }}</span>
      </label>
      <button :disabled="!selectedFile || creating" @click="createDocument">
        {{ creating ? '正在入库…' : '确认入库' }}
      </button>
    </section>

    <section class="admin-card">
      <div class="list-heading"><div><h2>资料清单</h2><p>共 {{ systemDocuments.length }} 份系统资料</p></div></div>
      <p v-if="loading && !systemDocuments.length" class="empty">正在读取…</p>
      <p v-else-if="!systemDocuments.length" class="empty">暂无系统资料</p>
      <article v-for="document in systemDocuments" :key="document.document_id" class="document-row">
        <div class="document-name"><span><Database :size="16" /></span><div><strong>{{ document.file_name }}</strong><small>{{ document.chunk_count }} 个知识片段</small></div></div>
        <div class="row-actions">
          <label class="replace-button">
            <input
              class="replace-input"
              type="file"
              accept=".pdf,.txt"
              :disabled="Boolean(activeDocumentId)"
              @change="replaceDocument(document, $event)"
            />
            <span><Replace :size="14" />{{ activeDocumentId === document.document_id ? '处理中…' : '整体替换' }}</span>
          </label>
          <button class="delete-button" :disabled="Boolean(activeDocumentId)" title="删除系统资料" @click="deleteTarget = document"><Trash2 :size="15" /></button>
        </div>
      </article>
    </section>
    <ConfirmDialog :open="Boolean(deleteTarget)" title="删除系统资料？" :description="deleteTarget ? `“${deleteTarget.file_name}”的原文件、数据库记录和向量片段都会被删除。` : ''" confirm-text="确认删除" :loading="Boolean(activeDocumentId)" @cancel="deleteTarget = null" @confirm="removeDocument" />
  </section>
</template>

<style scoped>
.secondary-action { min-height: 34px; display: inline-flex; align-items: center; gap: 7px; padding: 0 12px; border: 1px solid var(--border-default); border-radius: 6px; color: var(--text-default); background: #fff; cursor: pointer; }
.notice { margin-bottom: 12px; padding: 10px 12px; border: 1px solid transparent; border-radius: 6px; font-size: 12px; }
.notice.error { color: #982e2a; border-color: #efc3bf; background: #fff8f7; }
.notice.success { color: #176a4d; border-color: #badcca; background: #f4fbf7; }
.admin-card { padding: 17px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg-surface); }
.admin-card + .admin-card { margin-top: 16px; }
.admin-card h2 { margin: 0; color: var(--text-strong); font-size: 15px; }
.admin-card p { margin: 6px 0 0; }
.create-card { display: grid; grid-template-columns: auto minmax(260px, 1fr) minmax(220px, .6fr) auto; align-items: center; gap: 14px; }
.create-icon { width: 38px; height: 38px; display: grid; place-items: center; border-radius: 7px; color: var(--brand); background: #eaf4f1; }
.file-picker, .replace-button { position: relative; overflow: hidden; cursor: pointer; }
.file-picker input, .replace-button input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.file-picker span, .replace-button span, .create-card > button { min-height: 34px; display: inline-flex; align-items: center; justify-content: center; gap: 7px; padding: 0 11px; border: 1px solid var(--line); border-radius: 6px; background: white; font-size: 12px; cursor: pointer; }
.file-picker span { width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.create-card > button { color: white; border-color: var(--action); background: var(--action); }
button:disabled { opacity: .55; cursor: not-allowed; }
.list-heading, .document-row, .row-actions { display: flex; align-items: center; }
.list-heading, .document-row { justify-content: space-between; gap: 18px; }
.document-row { min-height: 58px; padding: 10px 4px; border-top: 1px solid #edf2f0; }
.document-name { min-width: 0; display: flex; align-items: center; gap: 10px; }
.document-name > span { width: 32px; height: 32px; display: grid; place-items: center; border-radius: 6px; color: var(--brand); background: #eaf4f1; }
.document-row strong, .document-row small { display: block; }
.document-row small { margin-top: 4px; color: var(--muted); font-size: 11px; }
.row-actions { gap: 8px; }
.delete-button { width: 34px; height: 34px; display: grid; place-items: center; padding: 0; border: 1px solid var(--border-default); border-radius: 6px; color: var(--danger); background: #fff; cursor: pointer; }
.empty { padding: 36px 0; text-align: center; }
@media (max-width: 760px) {
  .create-card, .document-row { align-items: stretch; flex-direction: column; }
  .create-card { display: flex; }
  .row-actions { justify-content: flex-end; }
}
</style>
