<script setup>
import { computed, onMounted, ref } from 'vue'
import { Clock3, FileText, RefreshCw, UploadCloud } from '@lucide/vue'

import ConfirmDialog from '../components/ConfirmDialog.vue'
import { getApiErrorMessage } from '../api/http'
import { getMySubmissions, withdrawSubmission } from '../api/profile'

const items = ref([])
const loading = ref(true)
const actingId = ref('')
const withdrawTarget = ref(null)
const errorMessage = ref('')
const successMessage = ref('')

const pendingCount = computed(() => items.value.filter((item) => item.status === 'pending_review').length)
const publishedCount = computed(() => items.value.filter((item) => item.status === 'published').length)

const statusLabels = {
  pending_review: '待审核',
  approved: '已通过',
  published: '已发布',
  rejected: '已拒绝',
  failed: '处理失败',
  withdrawn: '已撤回',
}

async function load() {
  loading.value = true
  errorMessage.value = ''
  try {
    items.value = (await getMySubmissions()).items
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    loading.value = false
  }
}

function requestWithdraw(item) {
  withdrawTarget.value = item
  successMessage.value = ''
}

async function confirmWithdraw() {
  if (!withdrawTarget.value || actingId.value) return
  const item = withdrawTarget.value
  actingId.value = item.submission_id
  errorMessage.value = ''
  try {
    await withdrawSubmission(item.submission_id)
    withdrawTarget.value = null
    successMessage.value = '资料已撤回。'
    await load()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    actingId.value = ''
  }
}

function formatDate(value) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

onMounted(load)
</script>

<template>
  <section class="platform-page">
    <header class="page-toolbar">
      <div>
        <span>MY SUBMISSIONS</span>
        <h1>我的资料</h1>
        <p>跟踪个人提交的审核、发布与失败状态。</p>
      </div>
      <div class="toolbar-actions">
        <button class="secondary-action" type="button" :disabled="loading" @click="load">
          <RefreshCw :size="15" :class="{ spinning: loading }" />刷新
        </button>
        <router-link class="primary-link" to="/knowledge"><UploadCloud :size="15" />提交资料</router-link>
      </div>
    </header>

    <div class="metric-grid document-metrics" aria-label="资料统计">
      <article><small>全部提交</small><strong>{{ items.length }}</strong><FileText :size="18" /></article>
      <article><small>等待审核</small><strong>{{ pendingCount }}</strong><Clock3 :size="18" /></article>
      <article><small>已发布</small><strong>{{ publishedCount }}</strong><UploadCloud :size="18" /></article>
    </div>

    <div v-if="successMessage" class="state-panel success" role="status">{{ successMessage }}</div>
    <div v-if="errorMessage" class="state-panel error" role="alert">{{ errorMessage }}</div>

    <section class="table-panel submissions-panel">
      <div class="panel-heading">
        <div><h2>提交记录</h2><span>{{ items.length }} 项</span></div>
      </div>
      <div v-if="loading" class="empty-panel">正在加载资料…</div>
      <div v-else-if="!items.length" class="empty-panel">
        <FileText :size="24" />
        <strong>暂无提交记录</strong>
        <p>你提交的 PDF 或 TXT 会在这里显示审核进度。</p>
        <router-link class="primary-link" to="/knowledge">提交第一份资料</router-link>
      </div>
      <div v-else class="responsive-table">
        <div class="submission-head"><span>文件</span><span>状态</span><span>审核说明</span><span>提交时间</span><span>操作</span></div>
        <div v-for="item in items" :key="item.submission_id" class="submission-row">
          <div class="file-cell"><span><FileText :size="16" /></span><strong :title="item.file_name">{{ item.file_name }}</strong></div>
          <span class="status-badge" :data-status="item.status">{{ statusLabels[item.status] || item.status }}</span>
          <span class="reason-cell" :title="item.rejection_reason || item.failure_reason">{{ item.rejection_reason || item.failure_reason || '—' }}</span>
          <span>{{ formatDate(item.submitted_at) }}</span>
          <button v-if="item.can_withdraw" class="text-action danger" type="button" @click="requestWithdraw(item)">撤回</button>
          <span v-else class="muted-action">—</span>
        </div>
      </div>
    </section>

    <ConfirmDialog
      :open="Boolean(withdrawTarget)"
      title="撤回这份资料？"
      :description="withdrawTarget ? `撤回后，“${withdrawTarget.file_name}”将不再进入审核流程。` : ''"
      confirm-text="确认撤回"
      :loading="Boolean(actingId)"
      @cancel="withdrawTarget = null"
      @confirm="confirmWithdraw"
    />
  </section>
</template>

<style scoped>
.toolbar-actions { display: flex; gap: 8px; }
.primary-link { display: inline-flex; align-items: center; gap: 7px; }
.secondary-action { min-height: 36px; display: inline-flex; align-items: center; gap: 7px; padding: 0 12px; border: 1px solid var(--border-default); border-radius: 6px; color: var(--text-default); background: var(--bg-surface); cursor: pointer; }
.secondary-action:disabled { cursor: wait; opacity: .6; }
.document-metrics article { position: relative; }
.document-metrics article > svg { position: absolute; top: 16px; right: 16px; color: var(--text-muted); }
.panel-heading > div { display: flex; align-items: center; gap: 9px; }
.panel-heading span { color: var(--text-muted); font-size: 11px; }
.submission-head, .submission-row { min-width: 820px; display: grid; grid-template-columns: minmax(220px, 1.5fr) .65fr minmax(180px, 1.1fr) 1fr .45fr; align-items: center; gap: 14px; padding: 11px 16px; }
.submission-head { color: var(--text-muted); background: var(--bg-subtle); font-size: 11px; font-weight: 700; }
.submission-row { min-height: 56px; border-top: 1px solid #edf1f0; color: var(--text-muted); font-size: 12px; }
.file-cell { min-width: 0; display: flex; align-items: center; gap: 10px; }
.file-cell > span { width: 30px; height: 30px; flex: 0 0 30px; display: grid; place-items: center; border-radius: 6px; color: var(--brand); background: #eaf4f1; }
.file-cell strong { overflow: hidden; color: var(--text-strong); text-overflow: ellipsis; white-space: nowrap; }
.reason-cell { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.text-action { padding: 4px 0; border: 0; background: transparent; cursor: pointer; text-align: left; }
.text-action.danger { color: var(--danger); }
.muted-action { color: #a2aca9; }
.empty-panel { min-height: 240px; display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 8px; padding: 28px; color: var(--text-muted); text-align: center; }
.empty-panel strong { color: var(--text-strong); }
.empty-panel p { margin: 0 0 7px; font-size: 12px; }
.spinning { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 640px) { .toolbar-actions { align-items: stretch; flex-direction: column; } .toolbar-actions > * { justify-content: center; } }
</style>
