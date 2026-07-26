<script setup>
import { onMounted, ref } from 'vue'
import {
  archiveAsset,
  getAssets,
  republishAsset,
  reviewKnowledgeAsset,
  scanKnowledgeGovernance,
  updateAsset,
} from '../api/adminPlatform'
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
function dateOnly(value) {
  return value ? new Date(value).toLocaleDateString() : '—'
}
function toIso(value) {
  if (!value?.trim()) return null
  return /^\d{4}-\d{2}-\d{2}$/.test(value.trim())
    ? `${value.trim()}T00:00:00Z`
    : new Date(value.trim()).toISOString()
}
async function edit(item) {
  const source = window.prompt('资料来源', item.source || '')
  if (source === null) return
  const tags = window.prompt('标签（使用中文逗号分隔）', item.tags.join('，'))
  if (tags === null) return
  const category = window.prompt('知识分类', item.category || '')
  if (category === null) return
  const department = window.prompt('科室标签', item.department || '')
  if (department === null) return
  const expiresAt = window.prompt('失效日期（YYYY-MM-DD，留空表示长期有效）', item.expires_at?.slice(0, 10) || '')
  if (expiresAt === null) return
  const reviewDueAt = window.prompt('下次复核日期（YYYY-MM-DD，留空表示不安排）', item.review_due_at?.slice(0, 10) || '')
  if (reviewDueAt === null) return
  actingId.value = item.document_id
  try {
    await updateAsset(item.document_id, {
      source: source.trim() || null,
      tags: tags.split(/[，,]/).map((value) => value.trim()).filter(Boolean),
      category: category.trim() || null,
      department: department.trim() || null,
      expires_at: toIso(expiresAt),
      review_due_at: toIso(reviewDueAt),
    })
    successMessage.value = '资产治理信息已更新。'
    await load()
  } catch (error) { errorMessage.value = getApiErrorMessage(error) }
  finally { actingId.value = '' }
}
async function markReviewed(item) {
  const nextDate = window.prompt('下次复核日期（YYYY-MM-DD）')
  if (!nextDate?.trim()) return
  const note = window.prompt('本次复核结论')
  if (!note?.trim()) return
  actingId.value = item.document_id
  try {
    await reviewKnowledgeAsset(item.document_id, {
      next_review_due_at: toIso(nextDate),
      note: note.trim(),
    })
    successMessage.value = '复核已完成，对应任务已关闭。'
    await load()
  } catch (error) { errorMessage.value = getApiErrorMessage(error) }
  finally { actingId.value = '' }
}
async function scanGovernance() {
  loading.value = true
  try {
    const result = await scanKnowledgeGovernance()
    successMessage.value = result.count ? `已创建 ${result.count} 个到期复核任务。` : '当前没有新的到期复核任务。'
    await load()
  } catch (error) { errorMessage.value = getApiErrorMessage(error) }
  finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <section class="platform-page">
    <header class="page-toolbar"><div><span>KNOWLEDGE ASSETS</span><h1>知识资产</h1><p>维护来源、分类、有效期和复核周期；只有 published 资料保留在生产检索集合。</p></div><div><el-button :loading="loading" @click="scanGovernance">扫描到期复核</el-button><el-button :loading="loading" @click="load">刷新</el-button></div></header>
    <div v-if="successMessage" class="state-panel success">{{ successMessage }}</div>
    <div v-if="errorMessage" class="state-panel error">{{ errorMessage }}</div>
    <div v-if="loading" class="state-panel">正在加载资产…</div>
    <div v-else-if="!items.length" class="state-panel">暂无知识资产。</div>
    <div v-else class="table-panel responsive-table">
      <div class="table-head-row"><span>文件</span><span>状态</span><span>来源/标签</span><span>治理</span><span>操作</span></div>
      <div v-for="item in items" :key="item.document_id" class="table-data-row">
        <strong :title="item.file_name">{{ item.file_name }}</strong>
        <span class="status-badge" :data-status="item.status">{{ item.status }}</span>
        <span>{{ item.source || '—' }}<small>{{ item.tags.join('、') || '无标签' }}</small></span>
        <span>{{ item.category || '未分类' }} / {{ item.department || '未指定科室' }}<small>v{{ item.version }} · 失效 {{ dateOnly(item.expires_at) }} · 复核 {{ dateOnly(item.review_due_at) }} · {{ item.review_status }}</small></span>
        <span class="asset-actions"><el-button :loading="actingId === item.document_id" @click="edit(item)">编辑</el-button><el-button v-if="item.review_status === 'in_review'" :loading="actingId === item.document_id" @click="markReviewed(item)">完成复核</el-button><el-button v-if="item.status === 'published'" :loading="actingId === item.document_id" @click="act(item, 'archive')">下线</el-button><el-button v-else-if="item.status === 'archived'" :loading="actingId === item.document_id" @click="act(item, 'republish')">重发</el-button></span>
      </div>
    </div>
  </section>
</template>
<style scoped>
.asset-actions{display:flex;flex-wrap:wrap;gap:6px}
</style>
