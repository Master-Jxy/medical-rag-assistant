<script setup>
import { onMounted, ref } from 'vue'
import { getApiErrorMessage } from '../api/http'
import { getMySubmissions, withdrawSubmission } from '../api/profile'

const items = ref([])
const loading = ref(true)
const actingId = ref('')
const errorMessage = ref('')
const successMessage = ref('')

async function load() {
  loading.value = true
  errorMessage.value = ''
  try { items.value = (await getMySubmissions()).items }
  catch (error) { errorMessage.value = getApiErrorMessage(error) }
  finally { loading.value = false }
}

async function withdraw(item) {
  if (!window.confirm(`确认撤回“${item.file_name}”？`)) return
  actingId.value = item.submission_id
  errorMessage.value = ''
  try {
    await withdrawSubmission(item.submission_id)
    successMessage.value = '资料已撤回。'
    await load()
  } catch (error) { errorMessage.value = getApiErrorMessage(error) }
  finally { actingId.value = '' }
}
onMounted(load)
</script>

<template>
  <section class="platform-page">
    <header class="page-toolbar">
      <div><span>SUBMISSIONS</span><h1>我的资料</h1><p>提交成功不等于发布，审核通过后才进入公共检索。</p></div>
      <router-link class="primary-link" to="/knowledge">提交资料</router-link>
    </header>
    <div v-if="successMessage" class="state-panel success">{{ successMessage }}</div>
    <div v-if="errorMessage" class="state-panel error">{{ errorMessage }}</div>
    <div v-if="loading" class="state-panel">正在加载资料…</div>
    <div v-else-if="!items.length" class="state-panel">暂无提交记录。</div>
    <div v-else class="table-panel responsive-table">
      <div class="table-head-row"><span>文件</span><span>状态</span><span>原因</span><span>提交时间</span><span>操作</span></div>
      <div v-for="item in items" :key="item.submission_id" class="table-data-row">
        <strong :title="item.file_name">{{ item.file_name }}</strong>
        <span class="status-badge" :data-status="item.status">{{ item.status }}</span>
        <span :title="item.rejection_reason || item.failure_reason">{{ item.rejection_reason || item.failure_reason || '—' }}</span>
        <span>{{ new Date(item.submitted_at).toLocaleString() }}</span>
        <el-button v-if="item.can_withdraw" :loading="actingId === item.submission_id" @click="withdraw(item)">撤回</el-button>
        <span v-else>—</span>
      </div>
    </div>
  </section>
</template>
