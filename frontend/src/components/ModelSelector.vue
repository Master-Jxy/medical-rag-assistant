<script setup>
import { computed, onMounted, ref } from 'vue'
import { Check, ChevronDown, Cpu, FlaskConical } from '@lucide/vue'

import { getModelCatalog } from '../api/models.js'

const props = defineProps({
  surface: { type: String, default: 'rag' },
})

const fallbackOptions = [
  { id: 'qwen', label: '通义千问', provider: 'DashScope', model_name: 'qwen3-max', enabled: true, status: 'available' },
  { id: 'deepseek', label: 'DeepSeek', provider: 'DeepSeek', model_name: null, enabled: false, status: 'testing' },
  { id: 'kimi', label: 'Kimi', provider: 'Moonshot AI', model_name: null, enabled: false, status: 'testing' },
]

const options = ref(fallbackOptions)
const activeModelId = ref('qwen')
const loading = ref(true)
const menu = ref(null)

const activeModel = computed(
  () => options.value.find((item) => item.id === activeModelId.value) || options.value[0],
)

const pricingLabel = computed(() => {
  const model = activeModel.value
  const input = model?.input_price_per_million_tokens_cny
  const output = model?.output_price_per_million_tokens_cny
  if (input == null || output == null) return '费用单价未配置'
  return `输入 ¥${Number(input).toFixed(2)} / 输出 ¥${Number(output).toFixed(2)}（每百万 Token）`
})

async function load() {
  try {
    const result = await getModelCatalog(props.surface)
    options.value = result.options?.length ? result.options : fallbackOptions
    activeModelId.value = result.active_model_id || 'qwen'
  } catch {
    options.value = fallbackOptions
  } finally {
    loading.value = false
  }
}

function selectModel(option) {
  if (!option.enabled) return
  activeModelId.value = option.id
  if (menu.value) menu.value.open = false
}

onMounted(load)
</script>

<template>
  <details ref="menu" class="model-selector">
    <summary :title="pricingLabel">
      <Cpu :size="14" />
      <span>{{ loading ? '读取模型' : activeModel.label }}</span>
      <small>{{ activeModel.model_name || '接入中' }}</small>
      <ChevronDown :size="13" />
    </summary>
    <div class="model-menu">
      <header>
        <strong>选择模型</strong>
        <small>{{ props.surface === 'agent' ? 'Agent 执行模型' : 'RAG 回答模型' }}</small>
      </header>
      <button
        v-for="option in options"
        :key="option.id"
        type="button"
        :class="{ active: option.id === activeModelId }"
        :disabled="!option.enabled"
        @click="selectModel(option)"
      >
        <span class="model-icon"><Cpu v-if="option.enabled" :size="15" /><FlaskConical v-else :size="15" /></span>
        <span class="model-copy">
          <strong>{{ option.label }}</strong>
          <small>{{ option.enabled ? `${option.provider} · ${option.model_name}` : `${option.provider} · 正在测试中` }}</small>
        </span>
        <Check v-if="option.id === activeModelId" :size="15" />
        <span v-else-if="!option.enabled" class="testing-tag">接入中</span>
      </button>
      <footer>{{ pricingLabel }}</footer>
    </div>
  </details>
</template>

<style scoped>
.model-selector { position: relative; }
.model-selector summary { min-height: 30px; display: inline-flex; align-items: center; gap: 6px; padding: 0 8px; border-radius: 7px; color: var(--ui-text-secondary, #526179); cursor: pointer; list-style: none; font-size: 12px; transition: background .18s ease, color .18s ease; }
.model-selector summary::-webkit-details-marker { display: none; }
.model-selector summary:hover { color: var(--ui-text-primary, #1d1d1f); background: rgba(94,123,255,.08); }
.model-selector summary small { max-width: 110px; overflow: hidden; color: var(--ui-text-tertiary, #8a8f98); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.model-selector[open] summary > svg:last-child { transform: rotate(180deg); }
.model-selector summary > svg:last-child { transition: transform .18s ease; }
.model-menu { position: absolute; z-index: 12; left: 0; bottom: calc(100% + 9px); width: 286px; padding: 8px; border: 1px solid rgba(255,255,255,.82); border-radius: 14px; background: rgba(250,252,255,.96); box-shadow: 0 18px 44px rgba(46,62,110,.18); backdrop-filter: blur(22px) saturate(160%); }
.model-menu header { display: flex; align-items: baseline; justify-content: space-between; padding: 7px 8px 9px; }
.model-menu header strong { color: var(--ui-text-primary, #1d1d1f); font-size: 12px; }
.model-menu header small, .model-menu footer { color: var(--ui-text-tertiary, #8a8f98); font-size: 10px; }
.model-menu button { width: 100%; display: grid; grid-template-columns: 30px minmax(0,1fr) auto; align-items: center; gap: 8px; padding: 8px; border: 0; border-radius: 9px; color: var(--ui-text-primary, #1d1d1f); background: transparent; text-align: left; cursor: pointer; }
.model-menu button:hover:not(:disabled), .model-menu button.active { background: rgba(94,123,255,.09); }
.model-menu button:disabled { color: #9298a5; cursor: not-allowed; opacity: .66; }
.model-icon { width: 30px; height: 30px; display: grid; place-items: center; border-radius: 8px; color: #4f6fec; background: rgba(94,123,255,.1); }
.model-menu button:disabled .model-icon { color: #8b92a0; background: #eef0f4; }
.model-copy { min-width: 0; display: grid; gap: 2px; }
.model-copy strong { font-size: 12px; }
.model-copy small { overflow: hidden; color: var(--ui-text-tertiary, #8a8f98); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.testing-tag { padding: 3px 6px; border-radius: 5px; color: #727985; background: #eceef2; font-size: 9px; }
.model-menu footer { margin: 5px 4px 0; padding: 8px 4px 3px; border-top: 1px solid rgba(103,118,151,.12); }
@media (max-width: 560px) { .model-selector summary small { display: none; } .model-menu { width: min(286px, calc(100vw - 42px)); } }
</style>
