<script setup>
defineProps({
  plan: { type: Array, default: () => [] },
  steps: { type: Array, default: () => [] },
  run: { type: Object, default: null },
})

const labels = {
  pending: '待执行',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  stopped: '已停止',
}
</script>

<template>
  <details
    v-if="plan.length || steps.length || run"
    class="run-progress"
    :open="steps.some((step) => ['running', 'failed'].includes(step.status))"
  >
    <summary>执行过程 · 按需调用（最多 5 次） · {{ labels[run?.status] || run?.status || '进行中' }}</summary>
    <ol v-if="plan.length" class="plan"><li v-for="item in plan" :key="item">{{ item }}</li></ol>
    <div v-for="step in steps" :key="step.id" class="step">
      <span :class="`dot ${step.status}`" />
      <div>
        <strong>第 {{ step.sequence }} 步 · {{ step.tool_name || step.node_name }}</strong>
        <small>{{ labels[step.status] || step.status }}</small>
        <p v-if="step.result_summary">{{ step.result_summary }}</p>
      </div>
    </div>
    <footer v-if="run">
      Token {{ run.used_tokens ?? 0 }} · 预估费用 ¥{{ Number(run.estimated_cost_cny || 0).toFixed(4) }}
    </footer>
  </details>
</template>

<style scoped>
.run-progress { margin-top: 10px; padding: 10px 12px; border: 1px solid #dfe7e3; border-radius: 6px; background: #fbfcfb; }
.run-progress summary { cursor: pointer; color: #315f4d; font-weight: 700; }
.plan { margin: 10px 0; padding-left: 22px; }
.step { display: grid; grid-template-columns: 9px 1fr; gap: 9px; margin: 10px 0; }
.dot { width: 8px; height: 8px; margin-top: 5px; border-radius: 50%; background: #7b8b84; }
.dot.completed { background: #2b7a58; }
.dot.failed { background: #b42318; }
.step div { display: grid; gap: 3px; }
.step small, footer { color: var(--muted); font-size: 12px; }
.step p { margin: 0; color: #46534f; }
footer { margin-top: 8px; }
</style>
