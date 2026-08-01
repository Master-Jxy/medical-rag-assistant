<script setup>
import { computed, onMounted, ref } from 'vue'
import { Activity, AlertTriangle, Ban, CircleDollarSign, CircleHelp, Gauge, RefreshCw, UsersRound, WalletCards } from '@lucide/vue'
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
    <header class="page-toolbar"><div><span>USAGE GOVERNANCE</span><h1>用量管理</h1><p>查看脱敏计量、异常调用与用户额度，不展示问答正文。</p></div><div class="toolbar-actions"><select v-model="days" aria-label="统计时间范围" @change="load"><option :value="1">今日</option><option :value="7">近 7 天</option><option :value="30">近 30 天</option></select><button class="secondary-action" type="button" :disabled="loading" @click="load"><RefreshCw :size="15" />刷新</button></div></header>
    <div v-if="errorMessage" class="state-panel error" role="alert">{{ errorMessage }}</div>
    <div v-if="loading" class="state-panel">正在加载用量统计…</div>
    <template v-else-if="overview">
      <section class="metric-grid usage-metrics"><article><span><Activity :size="17" /></span><div><small>总请求</small><strong>{{ overview.requests }}</strong></div></article><article><span><WalletCards :size="17" /></span><div><small>总 Token</small><strong>{{ overview.total_tokens.toLocaleString() }}</strong></div></article><article><span><CircleDollarSign :size="17" /></span><div><small>估算费用</small><strong>¥{{ overview.estimated_cost_cny.toFixed(4) }}</strong></div></article><article><span><Gauge :size="17" /></span><div><small>计量覆盖率</small><strong>{{ (overview.measurement_coverage * 100).toFixed(1) }}%</strong></div></article></section>
      <section class="risk-strip"><div><CircleHelp :size="16" /><span>未知计量</span><strong>{{ overview.unknown_calls }}</strong></div><div><AlertTriangle :size="16" /><span>失败调用</span><strong>{{ overview.failed_calls }}</strong></div><div><UsersRound :size="16" /><span>额度预警用户</span><strong>{{ overview.warning_users }}</strong></div><div><Ban :size="16" /><span>策略阻断事件</span><strong>{{ overview.would_block_events }}</strong></div><div><Gauge :size="16" /><span>预留低估</span><strong>{{ overview.reservation_underestimated_events }}</strong></div></section>
      <section class="admin-section"><header><div><Activity :size="16" /><h2>Token 趋势</h2></div><span>{{ days }} 天</span></header><div class="admin-trend" aria-label="管理员 Token 趋势"><div v-for="item in trend" :key="item.date"><span>{{ item.date }}</span><b>输入 {{ item.input_tokens.toLocaleString() }}</b><b>输出 {{ item.output_tokens.toLocaleString() }}</b></div><p v-if="!trend.length">暂无趋势数据</p></div></section>
      <section class="admin-section"><header><div><UsersRound :size="16" /><h2>高消耗与异常用户</h2></div><span>{{ users.length }} 个账号</span></header><div class="table-scroll"><table><thead><tr><th>用户</th><th>请求</th><th>Token</th><th>未知/失败</th><th>额度</th><th>剩余</th><th>状态</th><th v-if="canAdjust">操作</th></tr></thead><tbody><tr v-for="item in users" :key="item.user_id"><td>{{ item.email }}</td><td>{{ item.requests }}</td><td>{{ item.total_tokens }}</td><td>{{ item.unknown_calls }} / {{ item.failed_calls }}</td><td>{{ item.token_limit ?? '未建立周期' }}</td><td>{{ item.remaining_tokens ?? '—' }}</td><td><span class="status-badge" :data-status="item.quota_exhausted ? 'failed' : 'ready'">{{ userStatus(item) }}</span></td><td v-if="canAdjust"><button class="text-action" @click="openQuota(item)">调整额度</button></td></tr></tbody></table></div></section>
      <section class="admin-section"><header><div><Activity :size="16" /><h2>调用明细</h2></div><span>{{ records.length }} 条</span></header><form class="filters" @submit.prevent="load"><input v-model="filters.user_id" placeholder="用户 ID" aria-label="筛选用户ID"><input v-model="filters.model_name" placeholder="模型名称" aria-label="筛选模型"><select v-model="filters.surface" aria-label="筛选入口"><option value="">全部入口</option><option value="rag">RAG</option><option value="agent">Agent</option><option value="memory">记忆整理</option></select><select v-model="filters.status" aria-label="筛选状态"><option value="">全部状态</option><option value="completed">完成</option><option value="failed">失败</option><option value="cancelled">取消</option></select><button class="filter-action">筛选</button></form><div class="table-scroll"><table><thead><tr><th>时间</th><th>用户ID</th><th>入口</th><th>模型</th><th>状态</th><th>Token</th><th>耗时</th></tr></thead><tbody><tr v-for="item in records" :key="item.id"><td>{{ new Date(item.created_at).toLocaleString() }}</td><td>{{ item.user_id || '匿名' }}</td><td>{{ item.surface }}</td><td>{{ item.model_name }}</td><td>{{ item.measurement === 'unknown' ? '计量未知' : item.status }}</td><td>{{ item.total_tokens ?? '未知' }}</td><td>{{ item.latency_ms == null ? '暂无' : `${item.latency_ms} ms` }}</td></tr><tr v-if="!records.length"><td colspan="7">暂无明细</td></tr></tbody></table></div></section>
    </template>
    <div v-if="editing" class="modal-backdrop" role="presentation"><form class="quota-dialog" @submit.prevent="saveQuota"><h2>调整 {{ editing.email }} 的额度</h2><label>Token上限覆盖值<input v-model="quotaForm.token_limit_override" type="number" min="1" placeholder="留空恢复 1,000,000"></label><label>请求上限覆盖值<input v-model="quotaForm.request_limit_override" type="number" min="1" placeholder="留空恢复 500"></label><label>费用上限覆盖值（元，可选）<input v-model="quotaForm.estimated_cost_limit_cny_override" type="number" min="0.00000001" step="0.00000001" placeholder="留空表示不限制"></label><label>调整原因<textarea v-model="quotaForm.reason" required minlength="3" maxlength="200"></textarea></label><p>修改只影响数字额度，不改变账号角色；操作会写入超级管理员审计，历史用量账本不会改变。</p><div><button type="button" @click="editing = null">取消</button><button type="submit">确认调整</button></div></form></div>
  </section>
</template>

<style scoped>
.toolbar-actions{display:flex;gap:8px}.toolbar-actions select,.filters input,.filters select,.quota-dialog input,.quota-dialog textarea{min-height:34px;padding:0 9px;border:1px solid var(--border);border-radius:6px;background:#fff}.secondary-action{min-height:34px;display:inline-flex;align-items:center;gap:7px;padding:0 12px;border:1px solid var(--border);border-radius:6px;color:var(--text-default);background:#fff;cursor:pointer}.usage-metrics{grid-template-columns:repeat(4,1fr)}.usage-metrics article{min-height:86px;display:flex;align-items:center;justify-content:flex-start;gap:10px}.usage-metrics article>span{width:34px;height:34px;flex:0 0 34px;display:grid;place-items:center;border-radius:6px;color:var(--brand);background:#eaf4f1}.usage-metrics small{color:var(--muted);font-size:11px}.usage-metrics strong{display:block;margin-top:4px;font-size:18px}.risk-strip{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));margin-bottom:16px;border:1px solid var(--border);border-radius:8px;background:#fff;overflow:hidden}.risk-strip>div{min-height:52px;display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:7px;padding:0 12px;border-left:1px solid var(--border);color:var(--muted);font-size:10px}.risk-strip>div:first-child{border-left:0}.risk-strip svg{color:var(--warning)}.risk-strip strong{color:var(--text-strong);font-size:13px}.admin-section{margin-top:16px;border:1px solid var(--border);border-radius:8px;background:#fff;overflow:hidden}.admin-section>header{min-height:48px;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:0 15px;border-bottom:1px solid var(--border)}.admin-section>header>div{display:flex;align-items:center;gap:7px;color:var(--brand)}.admin-section h2{margin:0;color:var(--text-strong);font-size:13px}.admin-section>header>span{color:var(--muted);font-size:10px}.admin-trend{min-height:120px;display:grid;align-content:center;padding:10px 15px}.admin-trend>div{display:grid;grid-template-columns:110px 1fr 1fr;gap:12px;padding:8px 0;border-bottom:1px solid #edf1f0;color:var(--muted);font-size:11px}.admin-trend b{color:var(--text-default);font-weight:500}.admin-trend>p{color:var(--muted);font-size:11px}.table-scroll{overflow:auto}table{width:100%;border-collapse:collapse}th,td{padding:10px 12px;border-bottom:1px solid #edf1f0;text-align:left;white-space:nowrap;font-size:11px}th{color:var(--muted);background:var(--bg-subtle);font-weight:600}.text-action{padding:0;border:0;color:var(--action);background:transparent;cursor:pointer}.filters{display:flex;flex-wrap:wrap;gap:8px;padding:12px 15px;border-bottom:1px solid var(--border)}.filter-action{min-height:34px;padding:0 13px;border:0;border-radius:6px;color:#fff;background:var(--action);cursor:pointer}.modal-backdrop{position:fixed;inset:0;z-index:100;display:grid;place-items:center;padding:16px;background:rgba(12,18,17,.52)}.quota-dialog{display:grid;gap:12px;width:min(480px,100%);padding:20px;border:1px solid var(--border);border-radius:8px;background:#fff}.quota-dialog h2{margin:0;font-size:16px}.quota-dialog label{display:grid;gap:5px;color:var(--text-default);font-size:11px}.quota-dialog textarea{padding:9px;resize:vertical}.quota-dialog>p{margin:0;color:var(--muted);font-size:10px;line-height:17px}.quota-dialog div{display:flex;justify-content:flex-end;gap:8px}.quota-dialog button{min-height:34px;padding:0 12px;border:1px solid var(--border);border-radius:6px;background:#fff;cursor:pointer}.quota-dialog button[type="submit"]{color:#fff;border-color:var(--action);background:var(--action)}@media(max-width:1000px){.usage-metrics{grid-template-columns:1fr 1fr}.risk-strip{grid-template-columns:1fr 1fr}.risk-strip>div{border-top:1px solid var(--border);border-left:0}}@media(max-width:700px){.usage-metrics{grid-template-columns:1fr}.toolbar-actions{width:100%}.toolbar-actions>*{flex:1}.risk-strip{grid-template-columns:1fr}.filters>*{width:100%}.admin-trend>div{grid-template-columns:1fr}.admin-trend>div b{font-weight:500}}
</style>
