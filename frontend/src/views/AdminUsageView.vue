<script setup>
import { computed, onMounted, ref } from 'vue'
import { adjustUserQuota, getAdminUsageOverview, getAdminUsageRecords, getAdminUsageTrend, getAdminUsageUsers } from '../api/adminUsage'
import { getApiErrorMessage } from '../api/http'
import { useAuthSession } from '../auth/session'

const auth = useAuthSession()
const overview = ref(null), trend = ref([]), users = ref([]), records = ref([])
const loading = ref(true), errorMessage = ref(''), days = ref(30)
const filters = ref({ user_id: '', model_name: '', surface: '', status: '' })
const editing = ref(null), quotaForm = ref({ token_limit_override: '', request_limit_override: '', estimated_cost_limit_cny_override: '', reason: '' })
const canAdjust = computed(() => auth.user?.role === 'super_admin')
async function load() {
  loading.value = true; errorMessage.value = ''
  try {
    const [o, t, u, r] = await Promise.all([
      getAdminUsageOverview(days.value), getAdminUsageTrend(days.value),
      getAdminUsageUsers(), getAdminUsageRecords(filters.value),
    ])
    overview.value = o; trend.value = t.items || []; users.value = u.items || []; records.value = r.items || []
  } catch (error) { errorMessage.value = getApiErrorMessage(error) } finally { loading.value = false }
}
function openQuota(user) {
  editing.value = user
  quotaForm.value = {
    token_limit_override: user.token_limit_override ?? '',
    request_limit_override: user.request_limit_override ?? '',
    estimated_cost_limit_cny_override: user.estimated_cost_limit_cny_override ?? '',
    reason: '',
  }
}
async function saveQuota() {
  try {
    await adjustUserQuota(editing.value.user_id, {
      token_limit_override: quotaForm.value.token_limit_override ? Number(quotaForm.value.token_limit_override) : null,
      request_limit_override: quotaForm.value.request_limit_override ? Number(quotaForm.value.request_limit_override) : null,
      estimated_cost_limit_cny_override: quotaForm.value.estimated_cost_limit_cny_override ? Number(quotaForm.value.estimated_cost_limit_cny_override) : null,
      reason: quotaForm.value.reason,
    })
    editing.value = null; await load()
  } catch (error) { errorMessage.value = getApiErrorMessage(error) }
}
function userStatus(item) {
  if (item.quota_exhausted || item.warning_level === 'exhausted') return '已耗尽'
  if (item.warning_level === 'critical') return '95% 预警'
  if (item.warning_level === 'warning') return '80% 预警'
  if (item.unknown_calls || item.failed_calls) return '需关注'
  return '正常'
}
onMounted(load)
</script>

<template>
  <section class="platform-page">
    <header class="page-toolbar"><div><span>USAGE GOVERNANCE</span><h1>用量管理</h1><p>只展示脱敏计量，不展示问题、回答、Prompt或医学正文。</p></div><div><select v-model="days" aria-label="统计时间范围" @change="load"><option :value="1">今日</option><option :value="7">7天</option><option :value="30">30天</option></select><el-button :loading="loading" @click="load">刷新</el-button></div></header>
    <div v-if="errorMessage" class="state-panel error" role="alert">{{ errorMessage }}</div>
    <div v-if="loading" class="state-panel">正在加载用量统计…</div>
    <template v-else-if="overview">
      <section class="metric-grid"><article><span>总请求</span><strong>{{ overview.requests }}</strong></article><article><span>总Token</span><strong>{{ overview.total_tokens.toLocaleString() }}</strong></article><article><span>估算费用</span><strong>¥{{ overview.estimated_cost_cny.toFixed(4) }}</strong></article><article><span>计量覆盖率</span><strong>{{ (overview.measurement_coverage * 100).toFixed(1) }}%</strong></article><article><span>未知计量</span><strong>{{ overview.unknown_calls }}</strong></article><article><span>失败调用</span><strong>{{ overview.failed_calls }}</strong></article><article><span>额度预警用户</span><strong>{{ overview.warning_users }}</strong></article><article><span>策略若执行会阻断</span><strong>{{ overview.would_block_events }}</strong></article><article><span>预留低估</span><strong>{{ overview.reservation_underestimated_events }}</strong></article></section>
      <section class="table-panel"><h2>Token趋势</h2><div class="admin-trend" aria-label="管理员Token趋势"><div v-for="item in trend" :key="item.date"><span>{{ item.date }}</span><b>输入 {{ item.input_tokens.toLocaleString() }}</b><b>输出 {{ item.output_tokens.toLocaleString() }}</b></div><p v-if="!trend.length">暂无趋势数据</p></div></section>
      <section class="table-panel"><h2>高消耗与异常用户</h2><div class="table-scroll"><table><thead><tr><th>用户</th><th>请求</th><th>Token</th><th>未知/失败</th><th>额度</th><th>剩余</th><th>状态</th><th v-if="canAdjust">操作</th></tr></thead><tbody><tr v-for="item in users" :key="item.user_id"><td>{{ item.email }}</td><td>{{ item.requests }}</td><td>{{ item.total_tokens }}</td><td>{{ item.unknown_calls }} / {{ item.failed_calls }}</td><td>{{ item.token_limit ?? '未建立周期' }}</td><td>{{ item.remaining_tokens ?? '—' }}</td><td>{{ userStatus(item) }}</td><td v-if="canAdjust"><button @click="openQuota(item)">调整额度</button></td></tr></tbody></table></div></section>
      <section class="table-panel"><h2>调用明细</h2><form class="filters" @submit.prevent="load"><input v-model="filters.user_id" placeholder="用户ID" aria-label="筛选用户ID"><input v-model="filters.model_name" placeholder="模型" aria-label="筛选模型"><select v-model="filters.surface" aria-label="筛选入口"><option value="">全部入口</option><option value="rag">RAG</option><option value="agent">Agent</option><option value="memory">记忆整理</option></select><select v-model="filters.status" aria-label="筛选状态"><option value="">全部状态</option><option value="completed">完成</option><option value="failed">失败</option><option value="cancelled">取消</option></select><button>筛选</button></form><div class="table-scroll"><table><thead><tr><th>时间</th><th>用户ID</th><th>入口</th><th>模型</th><th>状态</th><th>Token</th><th>耗时</th></tr></thead><tbody><tr v-for="item in records" :key="item.id"><td>{{ new Date(item.created_at).toLocaleString() }}</td><td>{{ item.user_id || '匿名' }}</td><td>{{ item.surface }}</td><td>{{ item.model_name }}</td><td>{{ item.measurement === 'unknown' ? '计量未知' : item.status }}</td><td>{{ item.total_tokens ?? '未知' }}</td><td>{{ item.latency_ms == null ? '暂无' : `${item.latency_ms} ms` }}</td></tr><tr v-if="!records.length"><td colspan="7">暂无明细</td></tr></tbody></table></div></section>
    </template>
    <div v-if="editing" class="modal-backdrop" role="presentation"><form class="quota-dialog" @submit.prevent="saveQuota"><h2>调整 {{ editing.email }} 的额度</h2><label>Token上限覆盖值<input v-model="quotaForm.token_limit_override" type="number" min="1" placeholder="留空恢复 1,000,000"></label><label>请求上限覆盖值<input v-model="quotaForm.request_limit_override" type="number" min="1" placeholder="留空恢复 500"></label><label>费用上限覆盖值（元，可选）<input v-model="quotaForm.estimated_cost_limit_cny_override" type="number" min="0.00000001" step="0.00000001" placeholder="留空表示不限制"></label><label>调整原因<textarea v-model="quotaForm.reason" required minlength="3" maxlength="200"></textarea></label><p>修改只影响数字额度，不改变账号角色；操作会写入超级管理员审计，历史用量账本不会改变。</p><div><button type="button" @click="editing = null">取消</button><button type="submit">确认调整</button></div></form></div>
  </section>
</template>

<style scoped>
.page-toolbar>div:last-child{display:flex;gap:8px}.page-toolbar select,.filters input,.filters select,.quota-dialog input,.quota-dialog textarea{padding:9px;border:1px solid var(--border);border-radius:6px;background:#fff}.metric-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.metric-grid article,.table-panel{padding:16px;border:1px solid var(--border);border-radius:8px;background:#fff}.metric-grid span{color:var(--muted)}.metric-grid strong{display:block;margin-top:8px;font-size:22px}.table-panel{margin-top:16px}.table-panel h2{margin-top:0}.admin-trend{display:grid;gap:8px}.admin-trend>div{display:grid;grid-template-columns:110px 1fr 1fr;gap:12px;padding:8px;border-bottom:1px solid var(--border)}.table-scroll{overflow:auto}table{width:100%;border-collapse:collapse}th,td{padding:9px;border-bottom:1px solid var(--border);text-align:left;white-space:nowrap}.filters{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}.modal-backdrop{position:fixed;inset:0;z-index:20;display:grid;place-items:center;padding:16px;background:#0006}.quota-dialog{display:grid;gap:12px;width:min(480px,100%);padding:20px;border-radius:8px;background:#fff}.quota-dialog label{display:grid;gap:5px}.quota-dialog div{display:flex;justify-content:flex-end;gap:8px}@media(max-width:700px){.metric-grid{grid-template-columns:1fr 1fr}.page-toolbar{align-items:flex-start}.page-toolbar>div:last-child{width:100%}.filters>*{width:100%}.admin-trend>div{grid-template-columns:1fr}.admin-trend>div b{font-weight:500}}
</style>
