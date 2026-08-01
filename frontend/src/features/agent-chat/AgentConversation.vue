<script setup>
import { ref, watch } from 'vue'
import AgentMessageItem from './AgentMessageItem.vue'
import { scrollToLatest } from '../../utils/scroll.js'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  runDetails: { type: Object, default: () => ({}) },
  live: { type: Object, default: null },
})
defineEmits([
  'retry',
  'select-source',
  'select-artifact',
  'toggle-reference',
  'toggle-source-reference',
  'toggle-artifact-reference',
])

const conversationArea = ref(null)

watch(
  () => props.messages.map(
    (message) => `${message.id}:${message.content?.length || 0}:${message.status}`,
  ).join('|'),
  () => scrollToLatest(conversationArea),
  { immediate: true, flush: 'post' },
)
</script>

<template>
  <section
    ref="conversationArea"
    class="conversation"
    data-testid="agent-message-area"
    aria-live="polite"
  >
    <div v-if="!messages.length" class="empty">
      <strong>开始一段 Agent 对话</strong>
      <span>我会公开展示任务计划、工具调用和结果检查，完成后将过程折叠在最终回答上方。</span>
    </div>
    <AgentMessageItem
      v-for="message in messages"
      :key="message.id"
      :message="message"
      :run="runDetails[message.run_id] || runDetails[message.id] || null"
      :live="live?.assistantMessageId === message.id ? live : null"
      @retry="$emit('retry', $event)"
      @select-source="$emit('select-source', $event)"
      @select-artifact="$emit('select-artifact', $event)"
      @toggle-reference="$emit('toggle-reference', $event)"
      @toggle-source-reference="$emit('toggle-source-reference', $event)"
      @toggle-artifact-reference="$emit('toggle-artifact-reference', $event)"
    />
  </section>
</template>

<style scoped>
.conversation { min-height: 0; padding: 24px clamp(18px, 4vw, 52px) 138px; overflow: auto; }
.empty {
  max-width: 520px;
  margin: 92px auto;
  display: grid;
  gap: 8px;
  color: var(--muted);
  text-align: center;
  line-height: 1.7;
}
.empty strong { color: var(--ink); font-size: 18px; }
.empty span { font-size: 13px; }
@media (max-width: 760px) {
  .conversation { padding: 18px 12px 132px; }
}
</style>
