<script setup>
import { computed, onMounted, ref } from 'vue'
import { AlertCircle, CheckCircle2, RefreshCw, RotateCcw, Workflow } from '@lucide/vue'

import ConfirmDialog from '../components/ConfirmDialog.vue'
import { getJobs, retryJob } from '../api/adminPlatform'
import { getApiErrorMessage } from '../api/http'

const items = ref([])
const loading = ref(true)
const errorMessage = ref('')
const actingId = ref('')
const retryTarget = ref(null)
const failedCount = computed(() => items.value.filter((item) => item.status === 'failed').length)
const runningCount = computed(() => items.value.filter((item) => item.status === 'running').length)

async function load() {
  loading.value = true
  try {
    items.value = (await getJobs()).items
    errorMessage.value = ''
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    loading.value = false
  }
}

async function retry() {
  if (!retryTarget.value || actingId.value) return
  actingId.value = retryTarget.value.job_id
  try {
    await retryJob(retryTarget.value.job_id)
    retryTarget.value = null
    await load()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    actingId.value = ''
  }
}

onMounted(load)
</script>

<template>
  <section class="platform-page">
    <header class="page-toolbar"><div><span>PROCESSING JOBS</span><h1>任务中心</h1><p>跟踪解析、向量化和发布任务的执行状态。</p></div><button class="secondary-action" type="button" :disabled="loading" @click="load"><RefreshCw :size="15" />刷新</button></header>
    <div class="metric-grid job-metrics"><article><small>全部任务</small><strong>{{ items.length }}</strong><Workflow :size="18" /></article><article><small>执行中</small><strong>{{ runningCount }}</strong><RefreshCw :size="18" /></article><article><small>失败任务</small><strong>{{ failedCount }}</strong><AlertCircle :size="18" /></article></div>
    <div v-if="errorMessage" class="state-panel error">{{ errorMessage }}</div>
    <div v-if="loading" class="state-panel">正在加载任务…</div>
    <div v-else-if="!items.length" class="empty-panel"><CheckCircle2 :size="24" /><strong>暂无处理任务</strong><p>有文档进入处理队列后会显示在这里。</p></div>
    <section v-else class="table-panel responsive-table jobs-table"><div class="job-head"><span>任务类型</span><span>状态</span><span>进度</span><span>尝试次数</span><span>错误类型</span><span>操作</span></div><div v-for="item in items" :key="item.job_id" class="job-row"><div class="job-name"><span><Workflow :size="15" /></span><strong>{{ item.job_type }}</strong></div><span class="status-badge" :data-status="item.status">{{ item.status }}</span><div class="job-progress"><span><i :style="{ width: `${item.progress}%` }"></i></span><b>{{ item.progress }}%</b></div><span>第 {{ item.attempt_count }} 次</span><span :title="item.error_type">{{ item.error_type || '—' }}</span><button v-if="item.status === 'failed'" class="icon-action" type="button" title="重试任务" @click="retryTarget = item"><RotateCcw :size="15" /></button><span v-else>—</span></div></section>
    <ConfirmDialog :open="Boolean(retryTarget)" tone="warning" title="重试这个失败任务？" :description="retryTarget ? `任务类型：${retryTarget.job_type}。系统将创建新的执行尝试。` : ''" confirm-text="确认重试" :loading="Boolean(actingId)" @cancel="retryTarget = null" @confirm="retry" />
  </section>
</template>

<style scoped>
.secondary-action { min-height: 34px; display: inline-flex; align-items: center; gap: 7px; padding: 0 12px; border: 1px solid var(--border-default); border-radius: 6px; color: var(--text-default); background: #fff; cursor: pointer; }
.job-metrics article { position: relative; }
.job-metrics article > svg { position: absolute; top: 16px; right: 16px; color: var(--text-muted); }
.job-metrics article:last-child > svg { color: var(--danger); }
.job-head, .job-row { min-width: 880px; display: grid; grid-template-columns: 1.2fr .65fr 1.1fr .7fr 1fr .4fr; align-items: center; gap: 14px; padding: 11px 15px; }
.job-head { color: var(--text-muted); background: var(--bg-subtle); font-size: 11px; font-weight: 700; }
.job-row { min-height: 54px; border-top: 1px solid #edf1f0; color: var(--text-muted); font-size: 11px; }
.job-name { min-width: 0; display: flex; align-items: center; gap: 8px; }
.job-name > span { width: 28px; height: 28px; display: grid; place-items: center; border-radius: 6px; color: var(--brand); background: #eaf4f1; }
.job-name strong { color: var(--text-strong); }
.job-progress { display: flex; align-items: center; gap: 7px; }
.job-progress > span { width: 86px; height: 5px; overflow: hidden; border-radius: 3px; background: #e8efed; }
.job-progress i { display: block; height: 100%; background: var(--brand); }
.job-progress b { color: var(--text-default); font-size: 10px; }
.icon-action { width: 30px; height: 30px; display: grid; place-items: center; padding: 0; border: 1px solid var(--border-default); border-radius: 6px; color: var(--action); background: #fff; cursor: pointer; }
.empty-panel { min-height: 240px; display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 7px; border: 1px solid var(--border-default); border-radius: 8px; color: var(--text-muted); background: #fff; }
.empty-panel strong { color: var(--text-strong); }
.empty-panel p { margin: 0; font-size: 11px; }
</style>
