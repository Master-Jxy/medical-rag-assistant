<script setup>
import { onMounted, ref } from 'vue'
import { getApiErrorMessage } from '../api/http'
import { getMySubmissions, getPersonalStats } from '../api/profile'

const stats = ref(null)
const submissions = ref([])
const statsError = ref('')
const submissionsError = ref('')
const loading = ref(true)

async function load() {
  loading.value = true
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
  <section class="platform-page">
    <header class="page-toolbar">
      <div><span>WORKSPACE</span><h1>工作台</h1><p>查看个人使用情况和最近资料状态。</p></div>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </header>
    <div v-if="statsError" class="state-panel error">{{ statsError }}</div>
    <div v-else class="metric-grid" aria-label="个人统计">
      <article><small>我的会话</small><strong>{{ stats?.conversation_count ?? '—' }}</strong></article>
      <article><small>消息数量</small><strong>{{ stats?.message_count ?? '—' }}</strong></article>
      <article><small>我的资料</small><strong>{{ stats?.submitted_document_count ?? '—' }}</strong></article>
    </div>
    <section class="table-panel">
      <div class="panel-heading"><h2>最近资料</h2><router-link to="/my-documents">查看全部</router-link></div>
      <div v-if="submissionsError" class="state-panel error">{{ submissionsError }}</div>
      <div v-else-if="!loading && !submissions.length" class="state-panel">暂无资料，可前往“我的资料”提交。</div>
      <div v-else class="simple-table">
        <div v-for="item in submissions" :key="item.submission_id" class="table-row">
          <strong :title="item.file_name">{{ item.file_name }}</strong>
          <span class="status-badge" :data-status="item.status">{{ item.status }}</span>
        </div>
      </div>
    </section>
  </section>
</template>
