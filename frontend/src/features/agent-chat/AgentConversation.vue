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
      输入一项资料整理任务；运行时展示公开计划，消息、工具步骤、来源和产物会保存在当前会话。
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
.conversation { min-height: 0; padding: 14px 18px 120px; overflow: auto; }
.empty { max-width: 560px; margin: 80px auto; color: var(--muted); text-align: center; line-height: 1.7; }
</style>
