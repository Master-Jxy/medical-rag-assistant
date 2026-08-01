<script setup>
import { computed, onMounted, ref } from 'vue'
import { Archive, CalendarCheck, FileText, Pencil, RefreshCw, RotateCcw, ScanSearch, Tags } from '@lucide/vue'

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
import { getApiErrorMessage } from '../api/http'

const items = ref([])
const loading = ref(true)
const errorMessage = ref('')
const successMessage = ref('')
const actingId = ref('')
const editTarget = ref(null)
const reviewTarget = ref(null)
const actionTarget = ref(null)
const actionType = ref('')
const editForm = ref({ source: '', tags: '', category: '', department: '', expires_at: '', review_due_at: '' })
const reviewForm = ref({ next_review_due_at: '', note: '' })

const publishedCount = computed(() => items.value.filter((item) => item.status === 'published').length)
const reviewCount = computed(() => items.value.filter((item) => item.review_status === 'in_review').length)

async function load() {
  loading.value = true
  try {
    items.value = (await getAssets()).items
    errorMessage.value = ''
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    loading.value = false
  }
}

function dateOnly(value) {
  return value ? new Date(value).toLocaleDateString() : '—'
}

function toIso(value) {
  if (!value?.trim()) return null
  return /^\d{4}-\d{2}-\d{2}$/.test(value.trim()) ? `${value.trim()}T00:00:00Z` : new Date(value.trim()).toISOString()
}

function openEdit(item) {
  editTarget.value = item
  editForm.value = {
    source: item.source || '',
    tags: item.tags.join('，'),
    category: item.category || '',
    department: item.department || '',
    expires_at: item.expires_at?.slice(0, 10) || '',
    review_due_at: item.review_due_at?.slice(0, 10) || '',
  }
}

async function saveEdit() {
  if (!editTarget.value || actingId.value) return
  actingId.value = editTarget.value.document_id
  try {
    await updateAsset(editTarget.value.document_id, {
      source: editForm.value.source.trim() || null,
      tags: editForm.value.tags.split(/[，,]/).map((value) => value.trim()).filter(Boolean),
      category: editForm.value.category.trim() || null,
      department: editForm.value.department.trim() || null,
      expires_at: toIso(editForm.value.expires_at),
      review_due_at: toIso(editForm.value.review_due_at),
    })
    editTarget.value = null
    successMessage.value = '资产治理信息已更新。'
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
    else await republishAsset(item.document_id)
    actionTarget.value = null
    successMessage.value = actionType.value === 'archive' ? '资产已下线。' : '资产已重新发布。'
    await load()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    actingId.value = ''
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

onMounted(load)
</script>

<template>
  <section class="platform-page">
    <header class="page-toolbar">
      <div><span>KNOWLEDGE ASSETS</span><h1>知识资产</h1><p>维护来源、分类、有效期和复核周期。</p></div>
      <div class="toolbar-actions"><button class="secondary-action" type="button" :disabled="loading" @click="scanGovernance"><ScanSearch :size="15" />扫描到期复核</button><button class="secondary-action" type="button" :disabled="loading" @click="load"><RefreshCw :size="15" />刷新</button></div>
    </header>
    <div class="metric-grid asset-metrics"><article><small>全部资产</small><strong>{{ items.length }}</strong><FileText :size="18" /></article><article><small>生产检索中</small><strong>{{ publishedCount }}</strong><Tags :size="18" /></article><article><small>待完成复核</small><strong>{{ reviewCount }}</strong><CalendarCheck :size="18" /></article></div>
    <div v-if="successMessage" class="state-panel success">{{ successMessage }}</div>
    <div v-if="errorMessage" class="state-panel error">{{ errorMessage }}</div>
    <div v-if="loading" class="state-panel">正在加载资产…</div>
    <div v-else-if="!items.length" class="state-panel">暂无知识资产。</div>
    <section v-else class="table-panel responsive-table assets-table">
      <div class="asset-head"><span>文件</span><span>状态</span><span>来源与标签</span><span>治理信息</span><span>操作</span></div>
      <div v-for="item in items" :key="item.document_id" class="asset-row">
        <div class="asset-file"><span><FileText :size="16" /></span><div><strong :title="item.file_name">{{ item.file_name }}</strong><small>版本 v{{ item.version }}</small></div></div>
        <span class="status-badge" :data-status="item.status">{{ item.status }}</span>
        <div class="asset-meta"><strong>{{ item.source || '未设置来源' }}</strong><small>{{ item.tags.join('、') || '无标签' }}</small></div>
        <div class="asset-meta"><strong>{{ item.category || '未分类' }} · {{ item.department || '未指定科室' }}</strong><small>失效 {{ dateOnly(item.expires_at) }} · 复核 {{ dateOnly(item.review_due_at) }} · {{ item.review_status }}</small></div>
        <div class="asset-actions"><button class="icon-action" type="button" title="编辑治理信息" @click="openEdit(item)"><Pencil :size="15" /></button><button v-if="item.review_status === 'in_review'" class="icon-action success" type="button" title="完成复核" @click="openReview(item)"><CalendarCheck :size="15" /></button><button v-if="item.status === 'published'" class="icon-action danger" type="button" title="下线资产" @click="requestAction(item, 'archive')"><Archive :size="15" /></button><button v-else-if="item.status === 'archived'" class="icon-action" type="button" title="重新发布" @click="requestAction(item, 'republish')"><RotateCcw :size="15" /></button></div>
      </div>
    </section>

    <ModalDialog :open="Boolean(editTarget)" title="编辑知识资产" :description="editTarget?.file_name || ''" width="620px" @close="editTarget = null">
      <form class="asset-form" @submit.prevent="saveEdit"><label><span>资料来源</span><input v-model="editForm.source" placeholder="例如：卫健委公开资料" /></label><label><span>标签</span><input v-model="editForm.tags" placeholder="使用中文逗号分隔" /></label><div class="field-row"><label><span>知识分类</span><input v-model="editForm.category" /></label><label><span>科室标签</span><input v-model="editForm.department" /></label></div><div class="field-row"><label><span>失效日期</span><input v-model="editForm.expires_at" type="date" /></label><label><span>下次复核日期</span><input v-model="editForm.review_due_at" type="date" /></label></div></form>
      <template #footer><button class="secondary-action" type="button" :disabled="Boolean(actingId)" @click="editTarget = null">取消</button><button class="primary-action" type="button" :disabled="Boolean(actingId)" @click="saveEdit">{{ actingId ? '保存中…' : '保存修改' }}</button></template>
    </ModalDialog>

    <ModalDialog :open="Boolean(reviewTarget)" title="完成资产复核" :description="reviewTarget?.file_name || ''" width="520px" @close="reviewTarget = null">
      <form class="asset-form" @submit.prevent="saveReview"><label><span>下次复核日期</span><input v-model="reviewForm.next_review_due_at" type="date" required /></label><label><span>本次复核结论</span><textarea v-model="reviewForm.note" rows="4" required placeholder="记录资料仍然有效或需要更新的依据"></textarea></label></form>
      <template #footer><button class="secondary-action" type="button" :disabled="Boolean(actingId)" @click="reviewTarget = null">取消</button><button class="primary-action" type="button" :disabled="!reviewForm.next_review_due_at || !reviewForm.note.trim() || Boolean(actingId)" @click="saveReview">确认完成</button></template>
    </ModalDialog>

    <ConfirmDialog :open="Boolean(actionTarget)" :tone="actionType === 'archive' ? 'danger' : 'warning'" :title="actionType === 'archive' ? '下线这项知识资产？' : '重新发布这项知识资产？'" :description="actionTarget ? (actionType === 'archive' ? `“${actionTarget.file_name}”将从生产检索集合删除。` : `“${actionTarget.file_name}”将重建向量并重新加入检索。`) : ''" :confirm-text="actionType === 'archive' ? '确认下线' : '确认重发'" :loading="Boolean(actingId)" @cancel="actionTarget = null" @confirm="confirmAction" />
  </section>
</template>

<style scoped>
.toolbar-actions { display: flex; gap: 8px; }
.secondary-action, .primary-action { min-height: 34px; display: inline-flex; align-items: center; justify-content: center; gap: 7px; padding: 0 12px; border: 1px solid var(--border-default); border-radius: 6px; color: var(--text-default); background: var(--bg-surface); cursor: pointer; font-size: 12px; }
.primary-action { color: #fff; border-color: var(--action); background: var(--action); }
.secondary-action:disabled, .primary-action:disabled { cursor: wait; opacity: .55; }
.asset-metrics article { position: relative; }
.asset-metrics article > svg { position: absolute; top: 16px; right: 16px; color: var(--text-muted); }
.asset-head, .asset-row { min-width: 1000px; display: grid; grid-template-columns: minmax(220px, 1.25fr) .55fr minmax(180px, .9fr) minmax(300px, 1.4fr) 150px; align-items: center; gap: 14px; padding: 11px 15px; }
.asset-head { color: var(--text-muted); background: var(--bg-subtle); font-size: 11px; font-weight: 700; }
.asset-row { min-height: 62px; border-top: 1px solid #edf1f0; font-size: 11px; }
.asset-file { min-width: 0; display: flex; align-items: center; gap: 9px; }
.asset-file > span { width: 31px; height: 31px; flex: 0 0 31px; display: grid; place-items: center; border-radius: 6px; color: var(--brand); background: #eaf4f1; }
.asset-file > div, .asset-meta { min-width: 0; }
.asset-file strong, .asset-file small, .asset-meta strong, .asset-meta small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.asset-file strong, .asset-meta strong { color: var(--text-strong); font-size: 11px; }
.asset-file small, .asset-meta small { margin-top: 3px; color: var(--text-muted); font-size: 10px; }
.asset-actions { display: flex; gap: 5px; }
.icon-action { width: 30px; height: 30px; display: grid; place-items: center; padding: 0; border: 1px solid var(--border-default); border-radius: 6px; color: var(--text-muted); background: #fff; cursor: pointer; }
.icon-action.success { color: var(--success); }
.icon-action.danger { color: var(--danger); }
.asset-form { display: grid; gap: 13px; }
.asset-form label { display: grid; gap: 6px; color: var(--text-default); font-size: 11px; font-weight: 600; }
.asset-form input, .asset-form textarea { width: 100%; padding: 9px 10px; border: 1px solid var(--border-strong); border-radius: 6px; outline: 0; resize: vertical; }
.asset-form input:focus, .asset-form textarea:focus { border-color: var(--action); box-shadow: 0 0 0 3px rgba(37,99,235,.09); }
.field-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
@media (max-width: 640px) { .toolbar-actions { align-items: stretch; flex-direction: column; } .field-row { grid-template-columns: 1fr; } }
</style>
