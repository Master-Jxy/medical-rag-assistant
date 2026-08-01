<script setup>
import { computed, onMounted, ref } from 'vue'
import { Activity, CalendarDays, CircleDollarSign, Gauge, Layers3, WalletCards } from '@lucide/vue'
import { getQuota, getUsageDistribution, getUsageRecords, getUsageSummary, getUsageTrend } from '../../api/profile'
import { getApiErrorMessage } from '../../api/http'

const emit = defineEmits(['error'])
const quota = ref(null), summary = ref(null), records = ref([]), trend = ref([]), distribution = ref(null)
const loading = ref(true), days = ref(30)
const maxTrend = computed(() => Math.max(1, ...trend.value.map((item) => item.input_tokens + item.output_tokens)))
const usagePercent = computed(() => {
  if (!quota.value?.token_limit) return 0
  return Math.min(100, Math.round((quota.value.used_tokens / quota.value.token_limit) * 100))
})
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
  <section class="usage-panel">
    <header class="usage-header"><div><h2>用量与额度</h2><p>查看模型调用、Token 扣减和当前周期余额。</p></div><label><span>统计范围</span><select v-model="days" aria-label="用量时间范围" @change="load"><option :value="1">今日</option><option :value="7">近 7 天</option><option :value="30">近 30 天</option></select></label></header>
    <div v-if="loading" class="usage-state">正在加载用量…</div>
    <template v-else-if="quota && summary">
      <div v-if="warningText" class="quota-warning" :class="quota.warning_level" role="status">{{ warningText }}</div>
      <section class="quota-overview">
        <div class="quota-main">
          <div class="quota-title"><span><Gauge :size="18" /></span><div><small>本周期 Token 额度</small><strong>{{ quota.token_limit.toLocaleString() }} Token</strong></div><b>{{ usagePercent }}%</b></div>
          <div class="quota-track"><i :style="{ width: `${usagePercent}%` }"></i></div>
          <div class="quota-foot"><span>已使用 {{ quota.used_tokens.toLocaleString() }}</span><span>预留 {{ quota.reserved_tokens.toLocaleString() }}</span><strong>剩余 {{ quota.remaining_tokens.toLocaleString() }}</strong></div>
        </div>
        <div class="quota-side"><span><CalendarDays :size="17" /></span><div><small>周期重置</small><strong>{{ new Date(quota.period_end).toLocaleDateString() }}</strong></div></div>
      </section>

      <div class="usage-metrics">
        <article><span><Activity :size="17" /></span><div><small>请求次数</small><strong>{{ quota.used_requests }} / {{ quota.request_limit }}</strong></div></article>
        <article><span><WalletCards :size="17" /></span><div><small>剩余请求</small><strong>{{ quota.remaining_requests }}</strong></div></article>
        <article><span><Gauge :size="17" /></span><div><small>预计可问</small><strong>{{ quota.estimated_remaining_requests == null ? '样本不足' : `约 ${quota.estimated_remaining_requests} 次` }}</strong></div></article>
        <article><span><CircleDollarSign :size="17" /></span><div><small>{{ days }} 天调用</small><strong>{{ summary.requests }} 次</strong></div></article>
      </div>

      <div class="analytics-grid">
        <section class="analytics-panel">
          <header><div><Activity :size="16" /><h3>Token 趋势</h3></div><span>输入 {{ summary.input_tokens.toLocaleString() }} · 输出 {{ summary.output_tokens.toLocaleString() }}</span></header>
          <div class="trend" aria-label="输入输出 Token 趋势">
            <div v-for="item in trend" :key="item.date" class="trend-row"><span>{{ item.date }}</span><div><i class="input" :style="{ width: `${item.input_tokens / maxTrend * 100}%` }"></i><i class="output" :style="{ width: `${item.output_tokens / maxTrend * 100}%` }"></i></div><b>{{ item.input_tokens }} / {{ item.output_tokens }}</b></div>
            <p v-if="!trend.length" class="empty-analytics">暂无趋势数据</p>
          </div>
        </section>
        <section class="analytics-panel distribution-panel">
          <header><div><Layers3 :size="16" /><h3>使用分布</h3></div></header>
          <div class="distribution"><div><h4>按入口</h4><p v-for="item in distribution?.by_surface || []" :key="item.name"><span>{{ item.name }}</span><strong>{{ item.tokens.toLocaleString() }}</strong></p><p v-if="!distribution?.by_surface?.length" class="empty-analytics">暂无数据</p></div><div><h4>按模型</h4><p v-for="item in distribution?.by_model || []" :key="item.name"><span>{{ item.name }}</span><strong>{{ item.tokens.toLocaleString() }}</strong></p><p v-if="!distribution?.by_model?.length" class="empty-analytics">暂无数据</p></div></div>
        </section>
      </div>

      <section class="records-panel">
        <header><div><Activity :size="16" /><h3>调用记录</h3></div><span>{{ records.length }} 条</span></header>
        <div class="table-wrap"><table><thead><tr><th>时间</th><th>入口</th><th>模型</th><th>实际 / 额度扣减 Token</th><th>估算费用</th><th>耗时</th></tr></thead><tbody><tr v-for="item in records" :key="item.id"><td>{{ new Date(item.created_at).toLocaleString() }}</td><td><span class="surface-badge">{{ item.surface }}</span></td><td>{{ item.model_name }}</td><td>{{ tokenText(item) }}</td><td>{{ item.estimated_cost_cny == null ? '单价未配置' : `¥${item.estimated_cost_cny.toFixed(4)}` }}</td><td>{{ item.latency_ms == null ? '暂无' : `${item.latency_ms} ms` }}</td></tr><tr v-if="!records.length"><td colspan="6">暂无调用记录</td></tr></tbody></table></div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.usage-panel { border: 1px solid var(--border-default); border-radius: 8px; background: var(--bg-surface); }
.usage-header { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 16px; border-bottom: 1px solid var(--border-default); }
.usage-header h2 { margin: 0; color: var(--text-strong); font-size: 15px; }
.usage-header p { margin: 4px 0 0; color: var(--text-muted); font-size: 11px; }
.usage-header label { display: flex; align-items: center; gap: 8px; color: var(--text-muted); font-size: 11px; }
select { height: 34px; padding: 0 9px; border: 1px solid var(--border-strong); border-radius: 6px; color: var(--text-default); background: #fff; }
.usage-state { min-height: 220px; display: grid; place-items: center; color: var(--text-muted); font-size: 12px; }
.quota-warning { margin: 16px 16px 0; padding: 10px 12px; border: 1px solid #e2c578; border-radius: 6px; color: #71510d; background: #fff9e9; font-size: 12px; }
.quota-warning.critical, .quota-warning.exhausted { color: #8d2424; border-color: #e9aaa5; background: #fff5f4; }
.quota-overview { display: grid; grid-template-columns: minmax(0, 1fr) 210px; gap: 12px; margin: 16px; }
.quota-main, .quota-side { padding: 15px; border: 1px solid var(--border-default); border-radius: 7px; }
.quota-title { display: flex; align-items: center; gap: 10px; }
.quota-title > span, .quota-side > span, .usage-metrics article > span { width: 34px; height: 34px; flex: 0 0 34px; display: grid; place-items: center; border-radius: 6px; color: var(--brand); background: #eaf4f1; }
.quota-title > div { flex: 1; }
.quota-title small, .quota-title strong { display: block; }
.quota-title small, .quota-side small, .usage-metrics small { color: var(--text-muted); font-size: 11px; }
.quota-title strong { margin-top: 2px; color: var(--text-strong); font-size: 15px; }
.quota-title b { color: var(--brand); font-size: 17px; }
.quota-track { height: 7px; margin-top: 14px; overflow: hidden; border-radius: 4px; background: #e8efed; }
.quota-track i { display: block; height: 100%; border-radius: inherit; background: var(--brand); }
.quota-foot { display: flex; justify-content: space-between; gap: 12px; margin-top: 8px; color: var(--text-muted); font-size: 10px; }
.quota-foot strong { color: var(--text-strong); }
.quota-side { display: flex; align-items: center; gap: 10px; }
.quota-side strong, .usage-metrics strong { display: block; margin-top: 3px; color: var(--text-strong); font-size: 13px; }
.usage-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 0 16px 16px; }
.usage-metrics article { min-width: 0; display: flex; align-items: center; gap: 9px; padding: 12px; border: 1px solid var(--border-default); border-radius: 7px; }
.analytics-grid { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(260px, .65fr); gap: 12px; margin: 0 16px 16px; }
.analytics-panel, .records-panel { border: 1px solid var(--border-default); border-radius: 7px; }
.analytics-panel > header, .records-panel > header { min-height: 46px; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 0 13px; border-bottom: 1px solid var(--border-default); }
.analytics-panel header > div, .records-panel header > div { display: flex; align-items: center; gap: 7px; color: var(--brand); }
.analytics-panel h3, .records-panel h3 { margin: 0; color: var(--text-strong); font-size: 12px; }
.analytics-panel header > span, .records-panel header > span { color: var(--text-muted); font-size: 10px; }
.trend { min-height: 180px; display: grid; align-content: center; gap: 9px; padding: 13px; }
.trend-row { display: grid; grid-template-columns: 82px minmax(80px, 1fr) 100px; align-items: center; gap: 8px; color: var(--text-muted); font-size: 10px; }
.trend-row > div { display: grid; gap: 3px; }
.trend-row i { display: block; min-width: 2px; height: 5px; border-radius: 3px; }
.trend-row .input { background: var(--action); }
.trend-row .output { background: var(--brand); }
.trend-row b { color: var(--text-default); font-size: 10px; text-align: right; }
.distribution { min-height: 180px; display: grid; grid-template-columns: 1fr 1fr; }
.distribution > div { padding: 12px; }
.distribution > div + div { border-left: 1px solid var(--border-default); }
.distribution h4 { margin: 0 0 9px; color: var(--text-muted); font-size: 10px; }
.distribution p { display: flex; justify-content: space-between; gap: 10px; margin: 7px 0; color: var(--text-muted); font-size: 10px; }
.distribution p strong { color: var(--text-strong); }
.empty-analytics { align-self: center; justify-self: center; color: var(--text-muted); font-size: 11px; }
.records-panel { margin: 0 16px 16px; overflow: hidden; }
.table-wrap { overflow: auto; }
.table-wrap table { width: 100%; border-collapse: collapse; }
.table-wrap th, .table-wrap td { padding: 10px 12px; border-bottom: 1px solid #edf1f0; white-space: nowrap; text-align: left; font-size: 10px; }
.table-wrap th { color: var(--text-muted); background: var(--bg-subtle); font-weight: 600; }
.table-wrap td { color: var(--text-default); }
.surface-badge { display: inline-flex; padding: 2px 6px; border-radius: 4px; color: var(--brand); background: #eaf4f1; }
@media (max-width: 1000px) { .usage-metrics { grid-template-columns: 1fr 1fr; } .analytics-grid { grid-template-columns: 1fr; } }
@media (max-width: 700px) { .usage-header { align-items: flex-start; flex-direction: column; } .quota-overview { grid-template-columns: 1fr; } .usage-metrics { grid-template-columns: 1fr; } .quota-foot { flex-wrap: wrap; } .trend-row { grid-template-columns: 70px minmax(80px, 1fr); } .trend-row b { grid-column: 2; } .distribution { grid-template-columns: 1fr; } .distribution > div + div { border-top: 1px solid var(--border-default); border-left: 0; } }
</style>
