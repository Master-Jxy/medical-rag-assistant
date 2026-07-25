<script setup>
import { onMounted, ref } from 'vue'
import { getJobs, retryJob } from '../api/adminPlatform'
import { getApiErrorMessage } from '../api/http'
const items = ref([]); const loading = ref(true); const errorMessage = ref(''); const actingId = ref('')
async function load() { loading.value = true; try { items.value = (await getJobs()).items; errorMessage.value = '' } catch (e) { errorMessage.value = getApiErrorMessage(e) } finally { loading.value = false } }
async function retry(item) { if (!window.confirm('确认重试此失败任务？')) return; actingId.value = item.job_id; try { await retryJob(item.job_id); await load() } catch (e) { errorMessage.value = getApiErrorMessage(e) } finally { actingId.value = '' } }
onMounted(load)
</script>
<template><section class="platform-page"><header class="page-toolbar"><div><span>JOBS</span><h1>任务中心</h1><p>业务状态与处理任务状态分别记录。</p></div><el-button :loading="loading" @click="load">刷新</el-button></header><div v-if="errorMessage" class="state-panel error">{{ errorMessage }}</div><div v-if="loading" class="state-panel">正在加载任务…</div><div v-else-if="!items.length" class="state-panel">暂无处理任务。</div><div v-else class="table-panel responsive-table"><div class="table-head-row"><span>类型</span><span>状态</span><span>进度</span><span>错误</span><span>操作</span></div><div v-for="item in items" :key="item.job_id" class="table-data-row"><strong>{{ item.job_type }}</strong><span class="status-badge">{{ item.status }}</span><span>{{ item.progress }}% · 第{{ item.attempt_count }}次</span><span>{{ item.error_type || '—' }}</span><el-button v-if="item.status === 'failed'" :loading="actingId === item.job_id" @click="retry(item)">重试</el-button><span v-else>—</span></div></div></section></template>
