<script setup>
import { onMounted, ref } from 'vue'
import { getAudit } from '../api/adminPlatform'
import { getApiErrorMessage } from '../api/http'
const items = ref([]); const loading = ref(true); const errorMessage = ref('')
async function load() { loading.value = true; try { items.value = (await getAudit()).items; errorMessage.value = '' } catch (e) { errorMessage.value = getApiErrorMessage(e) } finally { loading.value = false } }
onMounted(load)
</script>
<template><section class="platform-page"><header class="page-toolbar"><div><span>AUDIT</span><h1>审计记录</h1><p>仅保存可追踪管理动作，不保存医学正文或密钥。</p></div><el-button :loading="loading" @click="load">刷新</el-button></header><div v-if="errorMessage" class="state-panel error">{{ errorMessage }}</div><div v-if="loading" class="state-panel">正在加载审计记录…</div><div v-else-if="!items.length" class="state-panel">暂无审计记录。</div><div v-else class="table-panel responsive-table"><div class="table-head-row"><span>动作</span><span>对象</span><span>操作者</span><span>结果</span><span>时间</span></div><div v-for="item in items" :key="item.event_id" class="table-data-row"><strong>{{ item.action }}</strong><span :title="item.object_id">{{ item.object_type }} / {{ item.object_id }}</span><span :title="item.actor_user_id">{{ item.actor_user_id }}</span><span class="status-badge">{{ item.result }}</span><span>{{ new Date(item.created_at).toLocaleString() }}</span></div></div></section></template>
