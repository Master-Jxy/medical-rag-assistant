<script setup>
import { onMounted, ref } from 'vue'
import { approveReview, getReviews, rejectReview } from '../api/adminPlatform'
import { getApiErrorMessage } from '../api/http'

const items = ref([])
const loading = ref(true)
const actingId = ref('')
const errorMessage = ref('')
const successMessage = ref('')

async function load() {
  loading.value = true
  errorMessage.value = ''
  try { items.value = (await getReviews({ status: 'pending_review' })).items }
  catch (error) { errorMessage.value = getApiErrorMessage(error) }
  finally { loading.value = false }
}
async function approve(item) {
  if (!window.confirm('批准后将开始向量化并发布到公共知识库，是否继续？')) return
  actingId.value = item.submission_id
  try { await approveReview(item.submission_id); successMessage.value = '发布任务已完成。'; await load() }
  catch (error) { errorMessage.value = getApiErrorMessage(error) }
  finally { actingId.value = '' }
}
async function reject(item) {
  const reason = window.prompt('请输入拒绝原因（至少2个字符）')
  if (!reason) return
  actingId.value = item.submission_id
  try { await rejectReview(item.submission_id, reason); successMessage.value = '资料已拒绝。'; await load() }
  catch (error) { errorMessage.value = getApiErrorMessage(error) }
  finally { actingId.value = '' }
}
onMounted(load)
</script>

<template>
  <section class="platform-page">
    <header class="page-toolbar"><div><span>REVIEW</span><h1>审核中心</h1><p>批准后才会产生向量调用并进入公共检索。</p></div><el-button :loading="loading" @click="load">刷新</el-button></header>
    <div v-if="successMessage" class="state-panel success">{{ successMessage }}</div>
    <div v-if="errorMessage" class="state-panel error">{{ errorMessage }}</div>
    <div v-if="loading" class="state-panel">正在加载待审核资料…</div>
    <div v-else-if="!items.length" class="state-panel">当前没有待审核资料。</div>
    <div v-else class="review-list">
      <article v-for="item in items" :key="item.submission_id" class="review-card">
        <header><div><strong :title="item.file_name">{{ item.file_name }}</strong><small>提交者 {{ item.submitter_id || '系统' }}</small></div><span class="status-badge">{{ item.status }}</span></header>
        <p class="preview-text">{{ item.preview_text || '无解析预览' }}</p>
        <div v-if="item.parse_quality?.counts" class="parse-quality">
          <span>文本页 {{ item.parse_quality.counts.text || 0 }}</span>
          <span>疑似表格 {{ item.parse_quality.counts.table_like || 0 }}</span>
          <span>扫描/图片风险 {{ item.parse_quality.counts.scanned_or_image || 0 }}</span>
        </div>
        <details v-if="item.parse_quality?.page_results?.length" class="page-quality">
          <summary>查看逐页解析结果（{{ item.parse_quality.page_results.length }} 页）</summary>
          <p v-for="page in item.parse_quality.page_results" :key="page.page">
            第 {{ page.page }} 页：{{ page.kind }}，文本 {{ page.text_chars }} 字，图片对象 {{ page.image_count }}
          </p>
        </details>
        <p v-for="warning in item.parse_warnings" :key="warning" class="parse-warning">⚠ {{ warning }}</p>
        <small>SHA-256：{{ item.content_hash }}</small>
        <footer><el-button :loading="actingId === item.submission_id" @click="reject(item)">拒绝</el-button><el-button type="primary" :loading="actingId === item.submission_id" @click="approve(item)">批准发布</el-button></footer>
      </article>
    </div>
  </section>
</template>
