<script setup>
import { computed, onMounted, ref } from 'vue'
import { MessageSquareWarning, RefreshCw, Star, ThumbsDown, ThumbsUp } from '@lucide/vue'

import ModalDialog from '../components/ModalDialog.vue'
import { getApiErrorMessage } from '../api/http.js'
import { getQualityOverview, getQualityReview, getQualityReviews, reviewQualityFeedback } from '../api/quality.js'

const overview = ref(null)
const queue = ref([])
const detail = ref(null)
const loading = ref(true)
const reviewing = ref(false)
const reviewNote = ref('')
const errorMessage = ref('')
const maxDaily = computed(() => Math.max(1, ...(overview.value?.daily_counts || []).map((day) => day.positive + day.negative)))

async function load() {
  loading.value = true
  try {
    const [metrics, reviews] = await Promise.all([getQualityOverview(), getQualityReviews()])
    overview.value = metrics
    queue.value = reviews.items
    errorMessage.value = ''
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    loading.value = false
  }
}

async function inspect(id) {
  try {
    detail.value = await getQualityReview(id)
    reviewNote.value = ''
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  }
}

async function resolve(status) {
  if (!detail.value || !reviewNote.value.trim() || reviewing.value) return
  reviewing.value = true
  try {
    await reviewQualityFeedback(detail.value.feedback.id, status, reviewNote.value.trim())
    detail.value = null
    await load()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    reviewing.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="platform-page">
    <header class="page-toolbar"><div><span>ANSWER QUALITY</span><h1>回答质量</h1><p>聚合用户反馈并完成问题回答的人工复核。</p></div><button class="secondary-action" type="button" :disabled="loading" @click="load"><RefreshCw :size="15" />刷新</button></header>
    <div v-if="errorMessage" class="state-panel error">{{ errorMessage }}</div>
    <div v-if="overview" class="metric-grid quality-metrics"><article><small>反馈总数</small><strong>{{ overview.total }}</strong><Star :size="18" /></article><article><small>好评率</small><strong>{{ overview.positive_rate == null ? '—' : `${(overview.positive_rate * 100).toFixed(1)}%` }}</strong><ThumbsUp :size="18" /></article><article><small>待复核</small><strong>{{ overview.pending_review }}</strong><MessageSquareWarning :size="18" /></article></div>
    <section v-if="overview?.daily_counts?.length" class="trend-panel"><header><h2>近 14 天反馈趋势</h2><div><span><i class="positive"></i>好评</span><span><i class="negative"></i>差评</span></div></header><div class="quality-trend"><div v-for="day in overview.daily_counts" :key="day.date"><span>{{ day.date }}</span><div><i class="positive" :style="{ width: `${day.positive / maxDaily * 100}%` }"></i><i class="negative" :style="{ width: `${day.negative / maxDaily * 100}%` }"></i></div><b>{{ day.positive }} / {{ day.negative }}</b></div></div></section>
    <div v-if="loading" class="state-panel">正在加载质量数据…</div>
    <div v-else-if="!queue.length" class="state-panel">暂无待复核反馈。</div>
    <section v-else class="table-panel responsive-table"><div class="quality-head"><span>问题类型</span><span>问题反馈</span><span>用户说明</span><span>状态</span><span>操作</span></div><div v-for="item in queue" :key="item.id" class="quality-row"><span>{{ item.question_category }}</span><span>{{ item.issue_category }}</span><span class="comment-cell" :title="item.comment">{{ item.comment || '—' }}</span><span class="status-badge" :data-status="item.review_status">{{ item.review_status }}</span><button class="text-action" type="button" @click="inspect(item.id)">复核详情</button></div></section>

    <ModalDialog :open="Boolean(detail)" title="复核回答" description="核对问题、回答与引用来源后记录处理结论。" width="720px" @close="detail = null">
      <div v-if="detail" class="review-detail"><section><small>用户问题</small><p>{{ detail.question_excerpt }}</p></section><section><small>模型回答</small><p>{{ detail.answer_excerpt }}</p></section><section><small>引用来源</small><p>{{ detail.source_names.join('、') || '无' }}</p></section><label><span>复核说明</span><textarea v-model="reviewNote" rows="3" maxlength="500" placeholder="填写复核结论或忽略原因"></textarea></label></div>
      <template #footer><button class="secondary-action" type="button" :disabled="reviewing" @click="detail = null">关闭</button><button class="secondary-action danger" type="button" :disabled="!reviewNote.trim() || reviewing" @click="resolve('dismissed')"><ThumbsDown :size="14" />忽略反馈</button><button class="primary-action" type="button" :disabled="!reviewNote.trim() || reviewing" @click="resolve('resolved')"><ThumbsUp :size="14" />标记已复核</button></template>
    </ModalDialog>
  </section>
</template>

<style scoped>
.secondary-action, .primary-action { min-height: 34px; display: inline-flex; align-items: center; justify-content: center; gap: 7px; padding: 0 12px; border: 1px solid var(--border-default); border-radius: 6px; color: var(--text-default); background: #fff; cursor: pointer; }
.secondary-action.danger { color: var(--danger); }
.primary-action { color: #fff; border-color: var(--action); background: var(--action); }
.secondary-action:disabled, .primary-action:disabled { cursor: wait; opacity: .55; }
.quality-metrics article { position: relative; }
.quality-metrics article > svg { position: absolute; top: 16px; right: 16px; color: var(--text-muted); }
.quality-metrics article:nth-child(2) > svg { color: var(--success); }
.quality-metrics article:nth-child(3) > svg { color: var(--warning); }
.trend-panel { margin-bottom: 16px; border: 1px solid var(--border-default); border-radius: 8px; background: #fff; }
.trend-panel > header { min-height: 48px; display: flex; align-items: center; justify-content: space-between; padding: 0 15px; border-bottom: 1px solid var(--border-default); }
.trend-panel h2 { margin: 0; color: var(--text-strong); font-size: 13px; }
.trend-panel header > div { display: flex; gap: 12px; color: var(--text-muted); font-size: 10px; }
.trend-panel header span { display: flex; align-items: center; gap: 5px; }
.trend-panel header i { width: 8px; height: 8px; border-radius: 2px; }
.positive { background: var(--success); }
.negative { background: var(--danger); }
.quality-trend { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 22px; padding: 13px 15px; }
.quality-trend > div { display: grid; grid-template-columns: 82px minmax(60px, 1fr) 48px; align-items: center; gap: 8px; color: var(--text-muted); font-size: 10px; }
.quality-trend > div > div { display: grid; gap: 3px; }
.quality-trend i { display: block; min-width: 2px; height: 5px; border-radius: 3px; }
.quality-trend b { color: var(--text-default); text-align: right; }
.quality-head, .quality-row { min-width: 780px; display: grid; grid-template-columns: 1fr 1fr 1.4fr .8fr .55fr; align-items: center; gap: 14px; padding: 11px 15px; }
.quality-head { color: var(--text-muted); background: var(--bg-subtle); font-size: 11px; font-weight: 700; }
.quality-row { min-height: 52px; border-top: 1px solid #edf1f0; color: var(--text-default); font-size: 11px; }
.comment-cell { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.text-action { padding: 3px 0; border: 0; color: var(--action); background: transparent; cursor: pointer; text-align: left; }
.review-detail { display: grid; gap: 12px; }
.review-detail section { padding: 11px; border: 1px solid var(--border-default); border-radius: 6px; background: var(--bg-subtle); }
.review-detail small { color: var(--text-muted); font-size: 10px; font-weight: 700; }
.review-detail p { margin: 6px 0 0; color: var(--text-default); font-size: 12px; line-height: 20px; white-space: pre-wrap; }
.review-detail label { display: grid; gap: 6px; color: var(--text-default); font-size: 11px; font-weight: 600; }
.review-detail textarea { width: 100%; padding: 9px 10px; border: 1px solid var(--border-strong); border-radius: 6px; outline: 0; resize: vertical; }
@media (max-width: 760px) { .quality-trend { grid-template-columns: 1fr; } }
</style>
