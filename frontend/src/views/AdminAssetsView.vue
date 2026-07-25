<script setup>
import { onMounted, ref } from 'vue'
import { archiveAsset, getAssets, republishAsset } from '../api/adminPlatform'
import { getApiErrorMessage } from '../api/http'

const items = ref([])
const loading = ref(true)
const errorMessage = ref('')
const successMessage = ref('')
const actingId = ref('')
async function load() {
  loading.value = true
  try { items.value = (await getAssets()).items; errorMessage.value = '' }
  catch (error) { errorMessage.value = getApiErrorMessage(error) }
  finally { loading.value = false }
}
async function act(item, action) {
  if (!window.confirm(action === 'archive' ? '下线后将从检索集合删除，是否继续？' : '重新发布会重建向量，是否继续？')) return
  actingId.value = item.document_id
  try {
    if (action === 'archive') await archiveAsset(item.document_id)
    else await republishAsset(item.document_id)
    successMessage.value = action === 'archive' ? '资产已下线。' : '资产已重新发布。'
    await load()
  } catch (error) { errorMessage.value = getApiErrorMessage(error) }
  finally { actingId.value = '' }
}
onMounted(load)
</script>

<template>
  <section class="platform-page">
    <header class="page-toolbar"><div><span>KNOWLEDGE ASSETS</span><h1>知识资产</h1><p>只有 published 资料保留在生产检索集合。</p></div><el-button :loading="loading" @click="load">刷新</el-button></header>
    <div v-if="successMessage" class="state-panel success">{{ successMessage }}</div>
    <div v-if="errorMessage" class="state-panel error">{{ errorMessage }}</div>
    <div v-if="loading" class="state-panel">正在加载资产…</div>
    <div v-else-if="!items.length" class="state-panel">暂无知识资产。</div>
    <div v-else class="table-panel responsive-table">
      <div class="table-head-row"><span>文件</span><span>状态</span><span>来源/标签</span><span>版本</span><span>操作</span></div>
      <div v-for="item in items" :key="item.document_id" class="table-data-row">
        <strong :title="item.file_name">{{ item.file_name }}</strong>
        <span class="status-badge" :data-status="item.status">{{ item.status }}</span>
        <span>{{ item.source || '—' }}<small>{{ item.tags.join('、') }}</small></span>
        <span>v{{ item.version }}</span>
        <span><el-button v-if="item.status === 'published'" :loading="actingId === item.document_id" @click="act(item, 'archive')">下线</el-button><el-button v-else-if="item.status === 'archived'" :loading="actingId === item.document_id" @click="act(item, 'republish')">重发</el-button></span>
      </div>
    </div>
  </section>
</template>
