<script setup>
import { onMounted, ref } from 'vue'
import { AlertTriangle, ArrowRight, BookOpenCheck, ClipboardCheck, Gauge, RefreshCw } from '@lucide/vue'
import { getApiErrorMessage } from '../api/http'
import { getAssets, getJobs, getReviews } from '../api/adminPlatform'

const metrics = ref({ pending: null, failed: null, published: null })
const errors = ref([])
const loading = ref(true)

async function load() {
  loading.value = true
  errors.value = []
  const results = await Promise.allSettled([
    getReviews({ status: 'pending_review', limit: 1 }),
    getJobs({ status: 'failed', limit: 1 }),
    getAssets({ status: 'published', limit: 1 }),
  ])
  const keys = ['pending', 'failed', 'published']
  results.forEach((result, index) => {
    if (result.status === 'fulfilled') metrics.value[keys[index]] = result.value.total
    else {
      metrics.value[keys[index]] = null
      errors.value.push(getApiErrorMessage(result.reason))
    }
  })
  loading.value = false
}

onMounted(load)
</script>

<template>
  <section class="platform-page">
    <header class="page-toolbar">
      <div><span>ADMINISTRATION</span><h1>管理概览</h1><p>关注审核积压、失败任务和已发布知识。</p></div>
      <button class="secondary-action" type="button" :disabled="loading" @click="load"><RefreshCw :size="15" />刷新数据</button>
    </header>
    <div v-if="errors.length" class="state-panel error">
      部分数据加载失败：{{ errors[0] }}
    </div>
    <div class="metric-grid" aria-label="管理统计">
      <router-link to="/admin/reviews"><small>待审核</small><strong>{{ metrics.pending ?? '—' }}</strong><ClipboardCheck :size="18" /></router-link>
      <router-link to="/admin/jobs"><small>失败任务</small><strong>{{ metrics.failed ?? '—' }}</strong><AlertTriangle :size="18" /></router-link>
      <router-link to="/admin/knowledge-assets"><small>已发布知识</small><strong>{{ metrics.published ?? '—' }}</strong><BookOpenCheck :size="18" /></router-link>
    </div>
    <section class="quick-links">
      <router-link to="/admin/reviews"><ClipboardCheck :size="18" /><strong>审核中心</strong><span>查看解析预览并决定是否发布</span><ArrowRight :size="15" /></router-link>
      <router-link to="/admin/knowledge-assets"><BookOpenCheck :size="18" /><strong>知识资产</strong><span>管理版本、标签、下线与重发</span><ArrowRight :size="15" /></router-link>
      <router-link to="/admin/telemetry"><Gauge :size="18" /><strong>运行统计</strong><span>查看当前进程运行指标</span><ArrowRight :size="15" /></router-link>
    </section>
  </section>
</template>

<style scoped>
.secondary-action { min-height: 34px; display: inline-flex; align-items: center; gap: 7px; padding: 0 12px; border: 1px solid var(--border-default); border-radius: 6px; color: var(--text-default); background: #fff; cursor: pointer; }
.metric-grid > a { position: relative; }
.metric-grid > a > svg { position: absolute; top: 16px; right: 16px; color: var(--text-muted); }
.metric-grid > a:nth-child(2) > svg { color: var(--danger); }
.quick-links a { position: relative; display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 5px 10px; }
.quick-links a > svg:first-child { grid-row: 1 / 3; color: var(--brand); }
.quick-links a > strong { color: var(--text-strong); font-size: 13px; }
.quick-links a > span { grid-column: 2; }
.quick-links a > svg:last-child { grid-column: 3; grid-row: 1 / 3; color: var(--text-muted); }
</style>
