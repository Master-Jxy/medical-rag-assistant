<script setup>
import { onMounted, ref } from 'vue'
import { getApiErrorMessage } from '../api/http.js'
import { getQualityOverview, getQualityReview, getQualityReviews, reviewQualityFeedback } from '../api/quality.js'
const overview = ref(null); const queue = ref([]); const detail = ref(null); const loading = ref(true); const errorMessage = ref('')
async function load() { loading.value = true; try { const [metrics, reviews] = await Promise.all([getQualityOverview(), getQualityReviews()]); overview.value = metrics; queue.value = reviews.items; errorMessage.value = '' } catch (error) { errorMessage.value = getApiErrorMessage(error) } finally { loading.value = false } }
async function inspect(id) { try { detail.value = await getQualityReview(id) } catch (error) { errorMessage.value = getApiErrorMessage(error) } }
async function resolve(status) { if (!detail.value) return; const note = window.prompt(status === 'resolved' ? '请输入复核结论' : '请输入忽略原因'); if (!note?.trim()) return; try { await reviewQualityFeedback(detail.value.feedback.id, status, note.trim()); detail.value = null; await load() } catch (error) { errorMessage.value = getApiErrorMessage(error) } }
onMounted(load)
</script>
<template>
  <section class="platform-page">
    <header class="page-toolbar"><div><span>QUALITY</span><h1>回答质量</h1><p>聚合用户反馈，并对问题回答进行人工复核。</p></div><el-button :loading="loading" @click="load">刷新</el-button></header>
    <div v-if="errorMessage" class="state-panel error">{{ errorMessage }}</div>
    <div v-if="overview" class="metric-grid"><article><small>反馈总数</small><strong>{{ overview.total }}</strong></article><article><small>好评率</small><strong>{{ overview.positive_rate == null ? '—' : `${(overview.positive_rate * 100).toFixed(1)}%` }}</strong></article><article><small>待复核</small><strong>{{ overview.pending_review }}</strong></article></div>
    <div v-if="overview?.daily_counts?.length" class="quality-trend"><strong>近 14 天反馈趋势</strong><span v-for="day in overview.daily_counts" :key="day.date">{{ day.date }}：{{ day.positive }} 好评 / {{ day.negative }} 差评</span></div>
    <div v-if="loading" class="state-panel">正在加载质量数据…</div><div v-else-if="!queue.length" class="state-panel">暂无待复核反馈。</div>
    <div v-else class="table-panel responsive-table"><div class="table-head-row"><span>问题类型</span><span>问题反馈</span><span>说明</span><span>状态</span><span>操作</span></div><div v-for="item in queue" :key="item.id" class="table-data-row"><span>{{ item.question_category }}</span><span>{{ item.issue_category }}</span><span>{{ item.comment || '—' }}</span><span class="status-badge">{{ item.review_status }}</span><el-button @click="inspect(item.id)">复核</el-button></div></div>
    <div v-if="detail" class="quality-dialog" role="dialog" aria-modal="true"><div><h2>复核回答</h2><small>问题</small><p>{{ detail.question_excerpt }}</p><small>回答</small><p>{{ detail.answer_excerpt }}</p><small>来源</small><p>{{ detail.source_names.join('、') || '无' }}</p><footer><el-button @click="detail = null">关闭</el-button><el-button @click="resolve('dismissed')">忽略</el-button><el-button type="primary" @click="resolve('resolved')">标记已复核</el-button></footer></div></div>
  </section>
</template>
<style scoped>
.quality-trend{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0;padding:14px;border:1px solid var(--border);border-radius:8px;background:#fff}.quality-trend strong{width:100%}.quality-trend span{font-size:12px;color:var(--muted)}.quality-dialog{position:fixed;inset:0;z-index:30;display:grid;place-items:center;padding:16px;background:rgba(17,28,24,.42)}.quality-dialog>div{width:min(680px,100%);max-height:80vh;overflow:auto;padding:22px;border-radius:8px;background:#fff}.quality-dialog h2{margin-top:0}.quality-dialog small{color:var(--muted)}.quality-dialog p{white-space:pre-wrap;line-height:1.6}.quality-dialog footer{display:flex;justify-content:flex-end;gap:8px}
</style>
