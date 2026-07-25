<script setup>
import { onMounted, ref } from 'vue'
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
      <el-button :loading="loading" @click="load">刷新</el-button>
    </header>
    <div v-if="errors.length" class="state-panel error">
      部分数据加载失败：{{ errors[0] }}
    </div>
    <div class="metric-grid" aria-label="管理统计">
      <router-link to="/admin/reviews"><small>待审核</small><strong>{{ metrics.pending ?? '—' }}</strong></router-link>
      <router-link to="/admin/jobs"><small>失败任务</small><strong>{{ metrics.failed ?? '—' }}</strong></router-link>
      <router-link to="/admin/knowledge-assets"><small>已发布知识</small><strong>{{ metrics.published ?? '—' }}</strong></router-link>
    </div>
    <section class="quick-links">
      <router-link to="/admin/reviews"><strong>审核中心</strong><span>查看解析预览并决定是否发布</span></router-link>
      <router-link to="/admin/knowledge-assets"><strong>知识资产</strong><span>管理版本、标签、下线与重发</span></router-link>
      <router-link to="/admin/telemetry"><strong>运行统计</strong><span>查看当前进程运行指标</span></router-link>
    </section>
  </section>
</template>
