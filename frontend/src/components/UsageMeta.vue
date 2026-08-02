<script setup>
import { computed } from 'vue'
import { Coins, Gauge, Sigma } from '@lucide/vue'

const props = defineProps({ usage: { type: Object, default: null } })

const details = computed(() => {
  const usage = props.usage
  if (!usage) return null
  const charged = Number(usage.charged_tokens || 0).toLocaleString()
  if (usage.measurement === 'not_applicable') {
    return {
      measurement: '未调用模型',
      breakdown: '实际 0 Token',
      charged: '扣减 0 Token',
      cost: '¥0',
      priced: true,
    }
  }
  if (usage.measurement === 'unknown') {
    return {
      measurement: '模型实际 Token 未知',
      breakdown: '供应商未返回计量',
      charged: `保守扣减 ${charged} Token`,
      cost: usage.estimated_cost_cny == null ? '费用待计量' : `估算 ¥${Number(usage.estimated_cost_cny).toFixed(4)}`,
      priced: usage.estimated_cost_cny != null,
    }
  }
  return {
    measurement: `模型实际 ${Number(usage.total_tokens || 0).toLocaleString()} Token`,
    breakdown: `输入 ${Number(usage.input_tokens || 0).toLocaleString()} / 输出 ${Number(usage.output_tokens || 0).toLocaleString()}`,
    charged: `额度扣减 ${charged} Token`,
    cost: usage.estimated_cost_cny == null ? '单价未配置' : `估算 ¥${Number(usage.estimated_cost_cny).toFixed(4)}`,
    priced: usage.estimated_cost_cny != null,
  }
})
</script>

<template>
  <div v-if="details" class="usage-meta" aria-label="本次模型用量">
    <span :title="details.breakdown"><Sigma :size="12" />{{ details.measurement }}<small>{{ details.breakdown }}</small></span>
    <span><Gauge :size="12" />{{ details.charged }}</span>
    <span :class="{ unpriced: !details.priced }"><Coins :size="12" />{{ details.cost }}</span>
  </div>
</template>

<style scoped>
.usage-meta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 9px; color: var(--muted); text-align: left; }
.usage-meta > span { min-height: 24px; display: inline-flex; align-items: center; gap: 5px; padding: 3px 7px; border: 1px solid rgba(103,118,151,.13); border-radius: 6px; background: rgba(247,249,252,.82); font-size: 10px; line-height: 1.35; }
.usage-meta svg { color: #6074a8; }
.usage-meta small { margin-left: 1px; color: #9299a7; font-size: 9px; }
.usage-meta .unpriced { color: #8c6734; border-color: rgba(217,141,52,.2); background: rgba(255,248,236,.8); }
@media (max-width: 560px) { .usage-meta small { display: none; } }
</style>
