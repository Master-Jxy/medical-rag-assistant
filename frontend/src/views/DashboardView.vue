<script setup>
import { onMounted, ref } from 'vue'
import { ArrowRight, Bot, FileText, Library, MessageSquareText, RefreshCw, UploadCloud } from '@lucide/vue'

import { getApiErrorMessage } from '../api/http'
import { getMySubmissions, getPersonalStats } from '../api/profile'

const stats = ref(null)
const submissions = ref([])
const statsError = ref('')
const submissionsError = ref('')
const loading = ref(true)

const statusLabels = {
  pending_review: '待审核', approved: '已通过', published: '已发布', rejected: '已拒绝', failed: '处理失败', withdrawn: '已撤回',
}

const quickActions = [
  { to: '/chat', title: '知识问答', copy: '基于公共知识库查找答案与引用', icon: MessageSquareText },
  { to: '/agent', title: '资料 Agent', copy: '调用工具完成多步骤资料任务', icon: Bot },
  { to: '/knowledge', title: '公共知识库', copy: '浏览已发布资料并提交新文档', icon: Library },
]

async function load() {
  loading.value = true
  statsError.value = ''
  submissionsError.value = ''
  const [statsResult, submissionsResult] = await Promise.allSettled([
    getPersonalStats(),
    getMySubmissions(),
  ])
  if (statsResult.status === 'fulfilled') stats.value = statsResult.value
  else statsError.value = getApiErrorMessage(statsResult.reason)
  if (submissionsResult.status === 'fulfilled') submissions.value = submissionsResult.value.items.slice(0, 5)
  else submissionsError.value = getApiErrorMessage(submissionsResult.reason)
  loading.value = false
}

onMounted(load)
</script>

<template>
  <section class="platform-page dashboard-page">
    <header class="page-toolbar">
      <div><span>WORKSPACE</span><h1>工作台</h1><p>集中查看个人会话、资料状态与常用入口。</p></div>
      <button class="secondary-action" type="button" :disabled="loading" @click="load">
        <RefreshCw :size="15" :class="{ spinning: loading }" />刷新数据
      </button>
    </header>

    <div v-if="statsError" class="state-panel error">{{ statsError }}</div>
    <div v-else class="metric-grid dashboard-metrics" aria-label="个人统计">
      <article><div><small>我的会话</small><strong>{{ stats?.conversation_count ?? '—' }}</strong></div><span><MessageSquareText :size="18" /></span></article>
      <article><div><small>消息数量</small><strong>{{ stats?.message_count ?? '—' }}</strong></div><span><Bot :size="18" /></span></article>
      <article><div><small>我的资料</small><strong>{{ stats?.submitted_document_count ?? '—' }}</strong></div><span><FileText :size="18" /></span></article>
    </div>

    <div class="dashboard-grid">
      <section class="table-panel recent-panel">
        <div class="panel-heading"><h2>最近资料</h2><router-link to="/my-documents">查看全部 <ArrowRight :size="14" /></router-link></div>
        <div v-if="submissionsError" class="state-panel error">{{ submissionsError }}</div>
        <div v-else-if="!loading && !submissions.length" class="empty-recent"><UploadCloud :size="22" /><strong>暂无资料</strong><p>提交资料后可在这里跟踪审核状态。</p></div>
        <div v-else class="simple-table">
          <div v-for="item in submissions" :key="item.submission_id" class="table-row">
            <div class="recent-file"><span><FileText :size="15" /></span><strong :title="item.file_name">{{ item.file_name }}</strong></div>
            <span class="status-badge" :data-status="item.status">{{ statusLabels[item.status] || item.status }}</span>
          </div>
          <div v-if="loading" class="table-loading">正在读取资料…</div>
        </div>
      </section>

      <section class="quick-panel">
        <div class="panel-heading"><h2>开始工作</h2></div>
        <nav aria-label="常用功能">
          <router-link v-for="item in quickActions" :key="item.to" :to="item.to">
            <span class="quick-icon"><component :is="item.icon" :size="18" /></span>
            <span class="quick-copy"><strong>{{ item.title }}</strong><small>{{ item.copy }}</small></span>
            <ArrowRight :size="15" />
          </router-link>
        </nav>
      </section>
    </div>
  </section>
</template>

<style scoped>
.secondary-action { min-height: 36px; display: inline-flex; align-items: center; gap: 7px; padding: 0 12px; border: 1px solid var(--border-default); border-radius: 6px; color: var(--text-default); background: var(--bg-surface); cursor: pointer; }
.secondary-action:disabled { cursor: wait; opacity: .6; }
.dashboard-metrics article { flex-direction: row; align-items: center; }
.dashboard-metrics article > div { display: flex; flex-direction: column; justify-content: space-between; align-self: stretch; }
.dashboard-metrics article > span { width: 38px; height: 38px; display: grid; place-items: center; border-radius: 7px; color: var(--brand); background: #eaf4f1; }
.dashboard-grid { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(290px, .8fr); gap: 16px; }
.panel-heading a { display: inline-flex; align-items: center; gap: 4px; }
.recent-file { min-width: 0; display: flex; align-items: center; gap: 9px; }
.recent-file > span { width: 28px; height: 28px; flex: 0 0 28px; display: grid; place-items: center; border-radius: 6px; color: var(--brand); background: #edf5f3; }
.empty-recent { min-height: 250px; display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 7px; color: var(--text-muted); text-align: center; }
.empty-recent strong { color: var(--text-strong); }
.empty-recent p { margin: 0; font-size: 12px; }
.table-loading { padding: 18px 16px; color: var(--text-muted); font-size: 12px; }
.quick-panel { border: 1px solid var(--border-default); border-radius: 8px; background: var(--bg-surface); }
.quick-panel nav { display: grid; }
.quick-panel nav a { min-height: 76px; display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 11px; padding: 12px 16px; border-top: 1px solid #edf1f0; }
.quick-panel nav a:hover { background: var(--bg-subtle); }
.quick-icon { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 7px; color: var(--brand); background: #eaf4f1; }
.quick-copy { min-width: 0; }
.quick-copy strong, .quick-copy small { display: block; }
.quick-copy strong { color: var(--text-strong); font-size: 13px; }
.quick-copy small { margin-top: 3px; color: var(--text-muted); font-size: 11px; line-height: 17px; }
.quick-panel nav a > svg { color: #98a4a1; }
.spinning { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 980px) { .dashboard-grid { grid-template-columns: 1fr; } }
@media (max-width: 640px) { .secondary-action { align-self: flex-start; } }
</style>
