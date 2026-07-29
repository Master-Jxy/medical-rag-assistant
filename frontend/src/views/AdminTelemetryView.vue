<script setup>
import { computed, onMounted, ref } from 'vue'

import { getTelemetryStats } from '../api/adminTelemetry.js'
import { getApiErrorMessage } from '../api/http.js'

const stats = ref(null)
const loading = ref(false)
const errorMessage = ref('')

const successRate = computed(() => {
  if (stats.value?.success_rate == null) return '暂无'
  return `${(stats.value.success_rate * 100).toFixed(1)}%`
})

const duration = (value) => (value == null ? '暂无' : `${Number(value).toFixed(1)} ms`)
const tokenLabel = computed(() => {
  if (!stats.value) return '暂无'
  if (!stats.value.known_model_calls && stats.value.unknown_model_calls) {
    return '模型未返回计量'
  }
  return `${stats.value.input_tokens || 0} / ${stats.value.output_tokens || 0}`
})
const costLabel = computed(() => {
  if (!stats.value) return '暂无'
  if (stats.value.known_model_calls && !stats.value.priced_model_calls) {
    return 'Token 已知，单价未配置'
  }
  return `¥ ${Number(stats.value.estimated_cost_cny || 0).toFixed(4)}`
})
const coverageLabel = computed(() =>
  stats.value?.measurement_coverage == null
    ? '暂无模型调用'
    : `${(stats.value.measurement_coverage * 100).toFixed(1)}%`,
)
const errorRows = computed(() => Object.entries(stats.value?.error_type_counts || {}))

async function loadStats() {
  loading.value = true
  errorMessage.value = ''
  try {
    stats.value = await getTelemetryStats()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    loading.value = false
  }
}

onMounted(loadStats)
</script>

<template>
  <section class="telemetry-page">
    <header>
      <div><span>OBSERVABILITY</span><h1>运行统计</h1></div>
      <button :disabled="loading" @click="loadStats">{{ loading ? '读取中…' : '刷新统计' }}</button>
    </header>

    <div v-if="errorMessage" class="notice error" role="alert">{{ errorMessage }}</div>
    <template v-if="stats">
      <section class="metric-grid">
        <article><small>请求总量</small><strong>{{ stats.request_total }}</strong></article>
        <article><small>成功率</small><strong>{{ successRate }}</strong></article>
        <article><small>平均耗时</small><strong>{{ duration(stats.average_duration_ms) }}</strong></article>
        <article><small>主动停止</small><strong>{{ stats.user_stop_count }}</strong></article>
        <article><small>Token 输入 / 输出</small><strong>{{ tokenLabel }}</strong></article>
        <article><small>估算费用</small><strong>{{ costLabel }}</strong></article>
        <article><small>计量覆盖率</small><strong>{{ coverageLabel }}</strong></article>
        <article><small>已知 / 未知模型调用</small><strong>{{ stats.known_model_calls }} / {{ stats.unknown_model_calls }}</strong></article>
        <article><small>未调用模型</small><strong>{{ stats.no_model_calls }}</strong></article>
      </section>

      <section class="telemetry-card">
        <h2>模型计量说明</h2>
        <div class="counter-row">
          <span>已配置价格 {{ stats.priced_model_calls }}</span>
          <span>单价未配置 {{ stats.unpriced_model_calls }}</span>
          <span v-if="stats.unknown_model_calls">模型未返回计量 {{ stats.unknown_model_calls }}</span>
          <span v-if="stats.no_model_calls">未调用模型 {{ stats.no_model_calls }}</span>
        </div>
        <p class="empty">费用为调用时单价快照计算的估算值；Embedding 与 Reranker 不计入这里。</p>
      </section>

      <section class="telemetry-card">
        <h2>阶段平均耗时</h2>
        <dl>
          <div><dt>查询构造</dt><dd>{{ duration(stats.stage_average_duration_ms.query_construction) }}</dd></div>
          <div><dt>向量检索</dt><dd>{{ duration(stats.stage_average_duration_ms.knowledge_retrieval) }}</dd></div>
          <div><dt>可选重排</dt><dd>{{ duration(stats.stage_average_duration_ms.rerank) }}</dd></div>
          <div><dt>模型生成</dt><dd>{{ duration(stats.stage_average_duration_ms.model_generation) }}</dd></div>
          <div><dt>工具（阶段9预留）</dt><dd>{{ duration(stats.stage_average_duration_ms.tool) }}</dd></div>
        </dl>
      </section>

      <section class="telemetry-card">
        <h2>保护与失败</h2>
        <div class="counter-row">
          <span>限流 {{ stats.rate_limit_count }}</span>
          <span>Redis降级 {{ stats.redis_degradation_count }}</span>
          <span>模型失败 {{ stats.failure_counts.model }}</span>
          <span>检索失败 {{ stats.failure_counts.retrieval }}</span>
          <span>持久化失败 {{ stats.failure_counts.persistence }}</span>
        </div>
        <p v-if="!errorRows.length" class="empty">暂无错误类型记录</p>
        <table v-else>
          <thead><tr><th>错误类型</th><th>次数</th></tr></thead>
          <tbody><tr v-for="[name, count] in errorRows" :key="name"><td>{{ name }}</td><td>{{ count }}</td></tr></tbody>
        </table>
      </section>
    </template>
  </section>
</template>

<style scoped>
.telemetry-page { padding: 48px 0 64px; }
header { display: flex; align-items: end; justify-content: space-between; gap: 24px; margin-bottom: 24px; }
header span { color: var(--primary); font-size: 11px; font-weight: 800; letter-spacing: .16em; }
header h1 { margin: 8px 0 0; font-size: 34px; }
button { padding: 9px 15px; border: 1px solid var(--line); border-radius: 8px; background: white; cursor: pointer; }
button:disabled { opacity: .55; }
.notice { margin-bottom: 14px; padding: 12px 15px; border-radius: 8px; }
.notice.error { color: #a33f2f; background: #fff0ed; }
.metric-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.metric-grid article, .telemetry-card { border: 1px solid var(--line); background: rgba(255,255,255,.9); }
.metric-grid article { padding: 20px; border-radius: 8px; }
.metric-grid small, dt { color: var(--muted); font-size: 12px; }
.metric-grid strong { display: block; margin-top: 9px; font-size: 21px; }
.telemetry-card { margin-top: 18px; padding: 22px; border-radius: 8px; }
.telemetry-card h2 { margin: 0 0 16px; font-size: 17px; }
dl { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin: 0; }
dl div { padding: 12px; border-radius: 8px; background: #f4f8f6; }
dd { margin: 5px 0 0; font-weight: 700; }
.counter-row { display: flex; flex-wrap: wrap; gap: 9px; }
.counter-row span { padding: 7px 10px; border-radius: 999px; background: #eef5f2; font-size: 12px; }
table { width: 100%; margin-top: 16px; border-collapse: collapse; }
th, td { padding: 10px; border-top: 1px solid var(--line); text-align: left; }
.empty { color: var(--muted); }
@media (max-width: 760px) {
  header { align-items: stretch; flex-direction: column; }
  .metric-grid { grid-template-columns: 1fr 1fr; }
  dl { grid-template-columns: 1fr 1fr; }
}
</style>
