<script setup>
import { computed } from 'vue'
const props = defineProps({ usage: { type: Object, default: null } })
const label = computed(() => {
  const usage = props.usage
  if (!usage) return ''
  if (usage.measurement === 'unknown') return '模型未返回计量'
  if (usage.measurement === 'not_applicable') return '未调用模型 · 0 Token · ¥0'
  const cost = usage.estimated_cost_cny == null ? '单价未配置' : `估算 ¥${Number(usage.estimated_cost_cny).toFixed(4)}`
  return `输入 ${Number(usage.input_tokens || 0).toLocaleString()} · 输出 ${Number(usage.output_tokens || 0).toLocaleString()} · ${cost}`
})
</script>
<template><div v-if="label" class="usage-meta">{{ label }}</div></template>
<style scoped>.usage-meta{margin-top:8px;color:var(--muted);font-size:12px;text-align:left}</style>
