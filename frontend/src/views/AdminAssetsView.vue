<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import {
  Archive,
  CalendarCheck,
  Database,
  FileText,
  Filter,
  Pencil,
  RefreshCw,
  Replace,
  RotateCcw,
  ScanSearch,
  Tags,
  Trash2,
  UploadCloud,
  X,
} from '@lucide/vue'

import ConfirmDialog from '../components/ConfirmDialog.vue'
import ModalDialog from '../components/ModalDialog.vue'
import {
  archiveAsset,
  getAssets,
  republishAsset,
  reviewKnowledgeAsset,
  scanKnowledgeGovernance,
  updateAsset,
} from '../api/adminPlatform'
import {
  createSystemDocument,
  deleteSystemDocument,
  replaceSystemDocument,
} from '../api/adminDocuments.js'
import { getApiErrorMessage } from '../api/http'

const SOURCE_OPTIONS = [
  { value: 'system', label: '系统资料' },
  { value: 'user_submission', label: '用户提交' },
  { value: 'legacy_upload', label: '历史资料' },
]
const STATUS_OPTIONS = [
  { value: 'published', label: '已发布' },
  { value: 'archived', label: '已下线' },
  { value: 'failed', label: '处理失败' },
]
const GOVERNANCE_OPTIONS = [
  { value: 'current', label: '复核有效' },
  { value: 'due', label: '复核到期' },
  { value: 'in_review', label: '复核处理中' },
  { value: 'expired', label: '资料已失效' },
]
const DEFAULT_TAGS = ['医学指南', '疾病科普', '诊疗路径', '药物资料', '检验检查', '医学影像', '健康管理']
const DEFAULT_CATEGORIES = ['疾病知识', '诊疗规范', '药物与用药', '检验与检查', '医学影像', '健康教育']
const DEFAULT_DEPARTMENTS = ['全科', '心血管内科', '神经内科', '呼吸内科', '消化内科', '内分泌科', '外科', '影像科']

const items = ref([])
const total = ref(0)
const loading = ref(true)
const errorMessage = ref('')
const successMessage = ref('')
const actingId = ref('')
const editTarget = ref(null)
const reviewTarget = ref(null)
const actionTarget = ref(null)
const actionType = ref('')
const selectedFile = ref(null)
const creating = ref(false)
const replacingId = ref('')

const filters = reactive({ status: '', source: '', tag: '', governance: '' })
const editForm = ref({ source: 'system', tags: [], category: '', department: '', expires_at: '', review_due_at: '' })
const reviewForm = ref({ next_review_due_at: '', note: '' })

const publishedCount = computed(() => items.value.filter((item) => item.status === 'published').length)
const systemCount = computed(() => items.value.filter((item) => item.is_system).length)
const reviewCount = computed(() => items.value.filter((item) => item.review_status === 'in_review' || item.is_expired).length)
const activeFilterCount = computed(() => Object.values(filters).filter(Boolean).length)
const tagOptions = computed(() => uniqueOptions(DEFAULT_TAGS, items.value.flatMap((item) => item.tags || []), editForm.value.tags))
const categoryOptions = computed(() => uniqueOptions(DEFAULT_CATEGORIES, items.value.map((item) => item.category), [editForm.value.category]))
const departmentOptions = computed(() => uniqueOptions(DEFAULT_DEPARTMENTS, items.value.map((item) => item.department), [editForm.value.department]))

function uniqueOptions(...groups) {
  return [...new Set(groups.flat().map((value) => String(value || '').trim()).filter(Boolean))]
}

function queryParams() {
  const params = { limit: 100 }
  if (filters.status) params.status = filters.status
  if (filters.source) params.source = filters.source
  if (filters.tag) params.tag = filters.tag
  if (filters.governance === 'expired') params.expired = true
  else if (filters.governance) params.review_status = filters.governance
  return params
}

async function load() {
  loading.value = true
  try {
    const result = await getAssets(queryParams())
    items.value = result.items || []
    total.value = result.total ?? items.value.length
    errorMessage.value = ''
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  Object.assign(filters, { status: '', source: '', tag: '', governance: '' })
  load()
}

function sourceLabel(value) {
  return SOURCE_OPTIONS.find((item) => item.value === value)?.label || value || '未设置来源'
}

function statusLabel(value) {
  return STATUS_OPTIONS.find((item) => item.value === value)?.label || value
}

function governanceLabel(item) {
  if (item.is_expired) return '资料已失效'
  return GOVERNANCE_OPTIONS.find((option) => option.value === item.review_status)?.label || '复核有效'
}

function dateOnly(value) {
  return value ? new Date(value).toLocaleDateString() : '未设置'
}

function toIso(value) {
  if (!value?.trim()) return null
  return /^\d{4}-\d{2}-\d{2}$/.test(value.trim()) ? `${value.trim()}T00:00:00Z` : new Date(value.trim()).toISOString()
}

function openEdit(item) {
  editTarget.value = item
  editForm.value = {
    source: item.source || (item.is_system ? 'system' : 'user_submission'),
    tags: [...(item.tags || [])],
    category: item.category || '',
    department: item.department || '',
    expires_at: item.expires_at?.slice(0, 10) || '',
    review_due_at: item.review_due_at?.slice(0, 10) || '',
  }
}

function toggleTag(tag) {
  const tags = editForm.value.tags
  editForm.value.tags = tags.includes(tag) ? tags.filter((item) => item !== tag) : [...tags, tag]
}

async function saveEdit() {
  if (!editTarget.value || actingId.value) return
  actingId.value = editTarget.value.document_id
  try {
    await updateAsset(editTarget.value.document_id, {
      source: editForm.value.source || null,
      tags: editForm.value.tags,
      category: editForm.value.category || null,
      department: editForm.value.department || null,
      expires_at: toIso(editForm.value.expires_at),
      review_due_at: toIso(editForm.value.review_due_at),
    })
    editTarget.value = null
    successMessage.value = '资产来源、标签和治理信息已更新。'
    await load()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    actingId.value = ''
  }
}

function openReview(item) {
  reviewTarget.value = item
  reviewForm.value = { next_review_due_at: '', note: '' }
}

async function saveReview() {
  if (!reviewTarget.value || !reviewForm.value.next_review_due_at || !reviewForm.value.note.trim() || actingId.value) return
  actingId.value = reviewTarget.value.document_id
  try {
    await reviewKnowledgeAsset(reviewTarget.value.document_id, {
      next_review_due_at: toIso(reviewForm.value.next_review_due_at),
      note: reviewForm.value.note.trim(),
    })
    reviewTarget.value = null
    successMessage.value = '复核已完成，对应任务已关闭。'
    await load()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    actingId.value = ''
  }
}

function requestAction(item, action) {
  actionTarget.value = item
  actionType.value = action
}

async function confirmAction() {
  if (!actionTarget.value || actingId.value) return
  const item = actionTarget.value
  actingId.value = item.document_id
  try {
    if (actionType.value === 'archive') await archiveAsset(item.document_id)
    else if (actionType.value === 'republish') await republishAsset(item.document_id)
    else await deleteSystemDocument(item.document_id)
    successMessage.value = actionType.value === 'archive'
      ? '资产已下线。'
      : actionType.value === 'republish' ? '资产已重新发布。' : '系统资料及其向量片段已删除。'
    actionTarget.value = null
    await load()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    actingId.value = ''
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
  try {
    const result = await createSystemDocument(selectedFile.value)
    successMessage.value = `${result.file_name} 已作为系统资料入库。`
    selectedFile.value = null
    await load()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    creating.value = false
  }
}

async function replaceDocument(item, event) {
  const file = event.target.files?.[0]
  if (!validateFile(file) || replacingId.value) return
  replacingId.value = item.document_id
  try {
    const result = await replaceSystemDocument(item.document_id, file)
    successMessage.value = `${item.file_name} 已整体替换为 ${result.file_name}。`
    await load()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    replacingId.value = ''
    event.target.value = ''
  }
}

async function scanGovernance() {
  loading.value = true
  try {
    const result = await scanKnowledgeGovernance()
    successMessage.value = result.count ? `已创建 ${result.count} 个到期复核任务。` : '当前没有新的到期复核任务。'
    await load()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    loading.value = false
  }
}

const actionDialog = computed(() => {
  if (actionType.value === 'delete-system') return {
    title: '删除系统资料？',
    description: actionTarget.value ? `“${actionTarget.value.file_name}”的原文件、数据库记录和向量片段都会被删除。` : '',
    confirm: '确认删除',
  }
  if (actionType.value === 'archive') return { title: '下线知识资产？', description: '下线后将从公共检索中移除，但保留治理记录。', confirm: '确认下线' }
  return { title: '重新发布知识资产？', description: '系统将重新建立向量索引并恢复公共检索。', confirm: '确认发布' }
})

onMounted(load)
</script>

<template>
  <section class="platform-page asset-workspace">
    <header class="page-toolbar">
      <div><span>KNOWLEDGE OPERATIONS</span><h1>知识资产</h1><p>统一管理用户提交和系统资料，维护来源、标签、状态与复核周期。</p></div>
      <div class="toolbar-actions"><button class="secondary-action" type="button" :disabled="loading" @click="scanGovernance"><ScanSearch :size="15" />扫描复核</button><button class="secondary-action" type="button" :disabled="loading" @click="load"><RefreshCw :size="15" />刷新</button></div>
    </header>

    <div class="asset-summary">
      <article><small>当前结果</small><strong>{{ total }}</strong><FileText :size="18" /></article>
      <article><small>已发布</small><strong>{{ publishedCount }}</strong><Tags :size="18" /></article>
      <article><small>系统资料</small><strong>{{ systemCount }}</strong><Database :size="18" /></article>
      <article><small>需治理</small><strong>{{ reviewCount }}</strong><CalendarCheck :size="18" /></article>
    </div>

    <details class="system-upload-panel">
      <summary><span><UploadCloud :size="17" /></span><div><strong>新增系统资料</strong><small>管理员直接维护的 PDF / TXT 会进入公共知识库</small></div><span class="summary-action">展开上传</span></summary>
      <div class="upload-body">
        <label class="file-picker"><input type="file" accept=".pdf,.txt" @change="selectCreateFile" /><span><FileText :size="14" />{{ selectedFile?.name || '选择 PDF / TXT，最大 10 MB' }}</span></label>
        <button class="primary-action" type="button" :disabled="!selectedFile || creating" @click="createDocument">{{ creating ? '正在入库…' : '确认入库' }}</button>
      </div>
    </details>

    <form class="asset-filters" @submit.prevent="load">
      <span class="filter-title"><Filter :size="16" />筛选资产<small v-if="activeFilterCount">{{ activeFilterCount }}</small></span>
      <label><span>来源</span><select v-model="filters.source"><option value="">全部来源</option><option v-for="option in SOURCE_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
      <label><span>状态</span><select v-model="filters.status"><option value="">全部状态</option><option v-for="option in STATUS_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
      <label><span>标签</span><select v-model="filters.tag"><option value="">全部标签</option><option v-for="tag in tagOptions" :key="tag" :value="tag">{{ tag }}</option></select></label>
      <label><span>治理信息</span><select v-model="filters.governance"><option value="">全部治理状态</option><option v-for="option in GOVERNANCE_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
      <button class="primary-action" type="submit">应用筛选</button>
      <button v-if="activeFilterCount" class="clear-filters" type="button" @click="resetFilters"><X :size="14" />清空</button>
    </form>

    <div v-if="successMessage" class="state-panel success">{{ successMessage }}</div>
    <div v-if="errorMessage" class="state-panel error">{{ errorMessage }}</div>
    <div v-if="loading" class="state-panel">正在加载资产…</div>
    <div v-else-if="!items.length" class="state-panel">当前筛选条件下没有知识资产。</div>

    <section v-else class="asset-table" aria-label="知识资产清单">
      <header><span>文件</span><span>来源 / 状态</span><span>标签与分类</span><span>治理信息</span><span>操作</span></header>
      <article v-for="item in items" :key="item.document_id">
        <div class="asset-file"><span><Database v-if="item.is_system" :size="16" /><FileText v-else :size="16" /></span><div><strong :title="item.file_name">{{ item.file_name }}</strong><small>v{{ item.version }} · {{ item.chunk_count }} 个片段</small></div></div>
        <div class="source-status"><strong>{{ sourceLabel(item.source) }}</strong><span class="status-badge" :data-status="item.status">{{ statusLabel(item.status) }}</span></div>
        <div class="asset-taxonomy"><div><span v-for="tag in item.tags" :key="tag">{{ tag }}</span><small v-if="!item.tags.length">无标签</small></div><small>{{ item.category || '未分类' }} · {{ item.department || '未指定科室' }}</small></div>
        <div class="governance"><strong :class="{ warning: item.is_expired || item.review_status !== 'current' }">{{ governanceLabel(item) }}</strong><small>失效 {{ dateOnly(item.expires_at) }}<br />复核 {{ dateOnly(item.review_due_at) }}</small></div>
        <div class="asset-actions">
          <button class="icon-action" type="button" title="编辑治理信息" @click="openEdit(item)"><Pencil :size="15" /></button>
          <button v-if="item.review_status === 'in_review'" class="icon-action success" type="button" title="完成复核" @click="openReview(item)"><CalendarCheck :size="15" /></button>
          <label v-if="item.is_system" class="icon-action file-action" title="整体替换"><input type="file" accept=".pdf,.txt" :disabled="Boolean(replacingId)" @change="replaceDocument(item, $event)" /><Replace :size="15" /></label>
          <button v-if="item.status === 'published'" class="icon-action" type="button" title="下线资产" @click="requestAction(item, 'archive')"><Archive :size="15" /></button>
          <button v-else-if="item.status === 'archived'" class="icon-action" type="button" title="重新发布" @click="requestAction(item, 'republish')"><RotateCcw :size="15" /></button>
          <button v-if="item.is_system" class="icon-action danger" type="button" title="永久删除系统资料" @click="requestAction(item, 'delete-system')"><Trash2 :size="15" /></button>
        </div>
      </article>
    </section>

    <ModalDialog :open="Boolean(editTarget)" title="编辑知识资产" :description="editTarget?.file_name || ''" width="680px" @close="editTarget = null">
      <form class="asset-form" @submit.prevent="saveEdit">
        <div class="field-row"><label><span>资料来源</span><select v-model="editForm.source"><option v-for="option in SOURCE_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option></select></label><label><span>知识分类</span><select v-model="editForm.category"><option value="">未分类</option><option v-for="category in categoryOptions" :key="category" :value="category">{{ category }}</option></select></label></div>
        <label><span>资料标签</span><div class="tag-selector"><button v-for="tag in tagOptions" :key="tag" type="button" :class="{ selected: editForm.tags.includes(tag) }" @click="toggleTag(tag)">{{ tag }}</button></div></label>
        <div class="field-row"><label><span>科室标签</span><select v-model="editForm.department"><option value="">未指定科室</option><option v-for="department in departmentOptions" :key="department" :value="department">{{ department }}</option></select></label><label><span>失效日期</span><input v-model="editForm.expires_at" type="date" /></label></div>
        <label><span>下次复核日期</span><input v-model="editForm.review_due_at" type="date" /></label>
      </form>
      <template #footer><button class="secondary-action" type="button" :disabled="Boolean(actingId)" @click="editTarget = null">取消</button><button class="primary-action" type="button" :disabled="Boolean(actingId)" @click="saveEdit">{{ actingId ? '保存中…' : '保存修改' }}</button></template>
    </ModalDialog>

    <ModalDialog :open="Boolean(reviewTarget)" title="完成资产复核" :description="reviewTarget?.file_name || ''" width="520px" @close="reviewTarget = null">
      <form class="asset-form" @submit.prevent="saveReview"><label><span>下次复核日期</span><input v-model="reviewForm.next_review_due_at" type="date" /></label><label><span>复核说明</span><textarea v-model="reviewForm.note" rows="4" maxlength="500" placeholder="记录本次复核依据和结论"></textarea></label></form>
      <template #footer><button class="secondary-action" type="button" :disabled="Boolean(actingId)" @click="reviewTarget = null">取消</button><button class="primary-action" type="button" :disabled="Boolean(actingId) || !reviewForm.next_review_due_at || !reviewForm.note.trim()" @click="saveReview">完成复核</button></template>
    </ModalDialog>

    <ConfirmDialog :open="Boolean(actionTarget)" :title="actionDialog.title" :description="actionDialog.description" :confirm-text="actionDialog.confirm" :loading="Boolean(actingId)" @cancel="actionTarget = null" @confirm="confirmAction" />
  </section>
</template>

<style scoped>
.asset-workspace { display: grid; gap: 16px; }
.asset-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.asset-summary article { position: relative; min-height: 88px; display: grid; align-content: center; gap: 4px; padding: 16px 18px; border: 1px solid rgba(92,108,158,.12); border-radius: 14px; background: rgba(255,255,255,.58); }
.asset-summary small { color: var(--muted); font-size: 11px; }
.asset-summary strong { color: var(--ink); font-size: 23px; font-variant-numeric: tabular-nums; }
.asset-summary svg { position: absolute; top: 16px; right: 16px; color: #5975df; }
.system-upload-panel { overflow: hidden; border: 1px solid rgba(92,108,158,.13); border-radius: 15px; background: rgba(255,255,255,.5); }
.system-upload-panel summary { min-height: 68px; display: grid; grid-template-columns: 38px minmax(0,1fr) auto; align-items: center; gap: 12px; padding: 10px 16px; cursor: pointer; list-style: none; }
.system-upload-panel summary::-webkit-details-marker { display: none; }
.system-upload-panel summary > span:first-child { width: 38px; height: 38px; display: grid; place-items: center; border-radius: 10px; color: #526fe4; background: rgba(94,123,255,.1); }
.system-upload-panel summary strong, .system-upload-panel summary small { display: block; }
.system-upload-panel summary strong { color: var(--ink); font-size: 13px; }
.system-upload-panel summary small { margin-top: 3px; color: var(--muted); font-size: 11px; }
.summary-action { color: #5c6d8c; font-size: 11px; }
.upload-body { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 10px; padding: 0 16px 16px 66px; }
.file-picker { position: relative; min-width: 0; }
.file-picker input, .file-action input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.file-picker span { min-height: 38px; display: flex; align-items: center; gap: 8px; padding: 0 12px; overflow: hidden; border: 1px dashed rgba(94,123,255,.28); border-radius: 9px; color: #58667d; background: rgba(255,255,255,.62); text-overflow: ellipsis; white-space: nowrap; }
.asset-filters { display: grid; grid-template-columns: auto repeat(4, minmax(120px,1fr)) auto auto; align-items: end; gap: 10px; padding: 13px; border: 1px solid rgba(92,108,158,.12); border-radius: 15px; background: rgba(255,255,255,.55); }
.filter-title { min-height: 38px; display: flex; align-items: center; gap: 7px; padding: 0 5px; color: var(--ink); font-size: 12px; font-weight: 700; white-space: nowrap; }
.filter-title small { min-width: 18px; height: 18px; display: grid; place-items: center; border-radius: 6px; color: #fff; background: #5e7bff; font-size: 9px; }
.asset-filters label, .asset-form label { display: grid; gap: 5px; color: #59677e; font-size: 10px; font-weight: 650; }
.asset-filters select, .asset-form select, .asset-form input, .asset-form textarea { width: 100%; min-height: 38px; padding: 0 10px; border: 1px solid rgba(92,108,158,.18); border-radius: 9px; outline: 0; color: var(--ink); background: rgba(255,255,255,.82); font: inherit; font-size: 12px; }
.asset-form textarea { padding-block: 9px; resize: vertical; }
.asset-filters select:focus, .asset-form select:focus, .asset-form input:focus, .asset-form textarea:focus { border-color: #6c82e7; box-shadow: 0 0 0 3px rgba(94,123,255,.1); }
.clear-filters { min-height: 38px; display: inline-flex; align-items: center; gap: 5px; padding: 0 7px; border: 0; color: #758099; background: transparent; cursor: pointer; font-size: 11px; }
.asset-table { overflow: auto; border: 1px solid rgba(92,108,158,.12); border-radius: 15px; background: rgba(255,255,255,.6); }
.asset-table > header, .asset-table > article { min-width: 980px; display: grid; grid-template-columns: minmax(210px,1.5fr) minmax(130px,.7fr) minmax(190px,1fr) minmax(170px,.9fr) 164px; align-items: center; gap: 14px; padding: 0 16px; }
.asset-table > header { min-height: 42px; color: #7b8497; background: rgba(238,242,250,.72); font-size: 10px; font-weight: 700; }
.asset-table > article { min-height: 78px; border-top: 1px solid rgba(92,108,158,.1); }
.asset-file { min-width: 0; display: flex; align-items: center; gap: 10px; }
.asset-file > span { width: 34px; height: 34px; flex: 0 0 34px; display: grid; place-items: center; border-radius: 9px; color: #5370df; background: rgba(94,123,255,.1); }
.asset-file strong, .asset-file small, .source-status strong, .governance strong, .governance small { display: block; }
.asset-file strong { overflow: hidden; color: var(--ink); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.asset-file small, .asset-taxonomy > small, .governance small { margin-top: 4px; color: var(--muted); font-size: 10px; line-height: 1.55; }
.source-status { display: grid; justify-items: start; gap: 7px; }
.source-status strong { color: #49566d; font-size: 11px; }
.status-badge { padding: 3px 7px; border-radius: 6px; color: #246a52; background: #e9f6f0; font-size: 9px; }
.status-badge[data-status="archived"], .status-badge[data-status="failed"] { color: #8a5b34; background: #fff3e7; }
.asset-taxonomy > div { display: flex; flex-wrap: wrap; gap: 4px; }
.asset-taxonomy > div span { padding: 3px 6px; border-radius: 5px; color: #4c61a8; background: rgba(94,123,255,.09); font-size: 9px; }
.asset-taxonomy > div small { color: var(--muted); font-size: 10px; }
.governance strong { color: #287157; font-size: 11px; }
.governance strong.warning { color: #a16527; }
.asset-actions { display: flex; justify-content: flex-end; gap: 5px; }
.icon-action { position: relative; width: 30px; height: 30px; display: grid; place-items: center; padding: 0; border: 1px solid rgba(92,108,158,.14); border-radius: 8px; color: #5c6d8d; background: rgba(255,255,255,.68); cursor: pointer; }
.icon-action:hover { color: #3658d3; border-color: rgba(94,123,255,.3); transform: translateY(-1px); }
.icon-action.success { color: #2f8667; }
.icon-action.danger { color: #bd5058; }
.file-action { overflow: hidden; }
.asset-form { display: grid; gap: 15px; }
.field-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.tag-selector { display: flex; flex-wrap: wrap; gap: 7px; padding: 10px; border: 1px solid rgba(92,108,158,.14); border-radius: 10px; background: rgba(248,250,254,.76); }
.tag-selector button { min-height: 28px; padding: 0 9px; border: 1px solid transparent; border-radius: 7px; color: #69758a; background: #edf0f5; cursor: pointer; font-size: 10px; }
.tag-selector button.selected { color: #3857c3; border-color: rgba(94,123,255,.22); background: rgba(94,123,255,.12); }
@media (max-width: 1100px) { .asset-filters { grid-template-columns: repeat(4,minmax(0,1fr)); } .filter-title { grid-column: 1 / -1; } }
@media (max-width: 760px) { .asset-summary { grid-template-columns: 1fr 1fr; } .asset-filters { grid-template-columns: 1fr 1fr; } .upload-body { grid-template-columns: 1fr; padding-left: 16px; } .field-row { grid-template-columns: 1fr; } }
@media (max-width: 480px) { .asset-summary, .asset-filters { grid-template-columns: 1fr; } .system-upload-panel summary { grid-template-columns: 38px minmax(0,1fr); } .summary-action { display: none; } }
</style>
