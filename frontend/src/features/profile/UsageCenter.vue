<script setup>
import { computed, onMounted, ref } from 'vue'
import { getQuota, getUsageDistribution, getUsageRecords, getUsageSummary, getUsageTrend } from '../../api/profile'
import { getApiErrorMessage } from '../../api/http'

const emit = defineEmits(['error'])
const quota = ref(null), summary = ref(null), records = ref([]), trend = ref([]), distribution = ref(null)
const loading = ref(true), days = ref(30)
const maxTrend = computed(() => Math.max(1, ...trend.value.map((item) => item.input_tokens + item.output_tokens)))
const warningText = computed(() => {
  if (!quota.value || quota.value.warning_level === 'normal') return ''
  if (quota.value.warning_level === 'exhausted') return '本周期额度已用尽，新请求可能被额度策略阻止。'
  if (quota.value.warning_level === 'critical') return '本周期额度已使用至少 95%，请留意剩余额度。'
  return '本周期额度已使用至少 80%。'
})
async function load() {
  loading.value = true
  try {
    const [q, s, r, t, d] = await Promise.all([getQuota(), getUsageSummary(days.value), getUsageRecords(), getUsageTrend(days.value), getUsageDistribution(days.value)])
    quota.value = q; summary.value = s; records.value = r.items || []; trend.value = t.items || []; distribution.value = d
  } catch (error) { emit('error', getApiErrorMessage(error)) } finally { loading.value = false }
}
function tokenText(item) {
  const charged = Number(item.charged_tokens || 0).toLocaleString()
  if (item.measurement === 'unknown') return `实际未知 · 扣减 ${charged}`
  if (item.measurement === 'not_applicable') return '实际 0 · 扣减 0'
  return `实际 ${Number(item.total_tokens || 0).toLocaleString()} · 扣减 ${charged}`
}
onMounted(load)
</script>

<template>
  <section class="panel">
    <header><div><h2>用量与额度</h2><p>未知计量不会用字符数冒充实际 Token。</p></div><select v-model="days" aria-label="用量时间范围" @change="load"><option :value="1">今日</option><option :value="7">7天</option><option :value="30">30天</option></select></header>
    <div v-if="loading" class="state-panel">正在加载用量…</div>
    <template v-else-if="quota && summary">
      <div v-if="warningText" class="quota-warning" :class="quota.warning_level" role="status">{{ warningText }}</div>
      <div class="metrics"><div><span>本周期额度</span><strong>{{ quota.token_limit.toLocaleString() }} Token</strong></div><div><span>已使用</span><strong>{{ quota.used_tokens.toLocaleString() }}</strong></div><div><span>已预留</span><strong>{{ quota.reserved_tokens.toLocaleString() }}</strong></div><div><span>剩余</span><strong>{{ quota.remaining_tokens.toLocaleString() }}</strong></div><div><span>请求次数</span><strong>{{ quota.used_requests }} / {{ quota.request_limit }}</strong></div><div><span>剩余请求</span><strong>{{ quota.remaining_requests }}</strong></div><div><span>重置时间</span><strong>{{ new Date(quota.period_end).toLocaleDateString() }}</strong></div><div><span>预计可问</span><strong>{{ quota.estimated_remaining_requests == null ? '样本不足' : `约 ${quota.estimated_remaining_requests} 次` }}</strong></div></div>
      <p>{{ days }}天 {{ summary.requests }} 次 · 输入 {{ summary.input_tokens.toLocaleString() }} · 输出 {{ summary.output_tokens.toLocaleString() }}</p>
      <div class="trend" aria-label="输入输出Token趋势"><div v-for="item in trend" :key="item.date" class="trend-row"><span>{{ item.date }}</span><i class="input" :style="{width:`${item.input_tokens/maxTrend*100}%`}"/><i class="output" :style="{width:`${item.output_tokens/maxTrend*100}%`}"/><b>{{ item.input_tokens }} / {{ item.output_tokens }}</b></div><p v-if="!trend.length">暂无趋势数据</p></div>
      <div class="distribution"><div><h3>按入口</h3><p v-for="item in distribution?.by_surface || []" :key="item.name">{{ item.name }}：{{ item.tokens.toLocaleString() }} Token</p><p v-if="!distribution?.by_surface?.length">暂无数据</p></div><div><h3>按模型</h3><p v-for="item in distribution?.by_model || []" :key="item.name">{{ item.name }}：{{ item.tokens.toLocaleString() }} Token</p><p v-if="!distribution?.by_model?.length">暂无数据</p></div></div>
      <div class="table-wrap"><table><thead><tr><th>时间</th><th>入口</th><th>模型</th><th>实际 / 额度扣减 Token</th><th>估算费用</th><th>耗时</th></tr></thead><tbody><tr v-for="item in records" :key="item.id"><td>{{ new Date(item.created_at).toLocaleString() }}</td><td>{{ item.surface }}</td><td>{{ item.model_name }}</td><td>{{ tokenText(item) }}</td><td>{{ item.estimated_cost_cny == null ? '单价未配置' : `¥${item.estimated_cost_cny.toFixed(4)}` }}</td><td>{{ item.latency_ms == null ? '暂无' : `${item.latency_ms} ms` }}</td></tr><tr v-if="!records.length"><td colspan="6">暂无调用记录</td></tr></tbody></table></div>
    </template>
  </section>
</template>

<style scoped>
.panel{margin-top:18px;padding:18px;border:1px solid var(--border);border-radius:8px;background:#fff}.panel header{display:flex;justify-content:space-between;gap:16px}.panel h2{margin:0}.panel header p{margin:5px 0;color:var(--muted)}select{height:36px;padding:0 10px;border:1px solid var(--border);border-radius:6px;background:#fff}.quota-warning{margin-top:14px;padding:10px 12px;border:1px solid #c99524;border-radius:6px;background:#fff8df;color:#71510d}.quota-warning.critical,.quota-warning.exhausted{border-color:#c94b4b;background:#fff0f0;color:#8d2424}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}.metrics div,.distribution>div{border:1px solid var(--border);border-radius:6px;padding:12px}.metrics span{display:block;color:var(--muted);font-size:13px}.metrics strong{display:block;margin-top:6px}.trend{display:grid;gap:7px;margin:16px 0}.trend-row{display:grid;grid-template-columns:90px minmax(2px,1fr) minmax(2px,1fr) 110px;gap:7px;align-items:center;font-size:12px}.trend-row i{display:block;height:8px;border-radius:4px}.trend-row .input{background:#2878c8}.trend-row .output{background:#2f8f72}.distribution{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:16px 0}.distribution h3{margin:0 0 8px}.distribution p{margin:5px 0}.table-wrap{overflow:auto}.table-wrap table{width:100%;border-collapse:collapse}.table-wrap th,.table-wrap td{padding:9px;text-align:left;border-bottom:1px solid var(--border);white-space:nowrap}@media(max-width:700px){.panel header{align-items:flex-start;flex-direction:column}.metrics{grid-template-columns:1fr 1fr}.distribution{grid-template-columns:1fr}.trend-row{grid-template-columns:76px minmax(2px,1fr) minmax(2px,1fr)}.trend-row b{grid-column:2/4}}
</style>
