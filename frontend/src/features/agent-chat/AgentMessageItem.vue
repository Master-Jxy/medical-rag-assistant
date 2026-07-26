<script setup>
import AgentRunProgress from './AgentRunProgress.vue'

defineProps({
  message: { type: Object, required: true },
  run: { type: Object, default: null },
  live: { type: Object, default: null },
})
defineEmits(['retry', 'select-source', 'select-artifact', 'toggle-reference'])
</script>

<template>
  <article class="message" :class="message.role">
    <header>
      <strong>{{ message.role === 'user' ? '你' : '资料 Agent' }}</strong>
      <span>{{ message.status }}</span>
    </header>
    <div class="content">{{ message.content || live?.output || '正在处理…' }}</div>
    <AgentRunProgress
      v-if="message.role === 'assistant'"
      :plan="live?.plan || []"
      :steps="live?.steps || run?.steps || []"
      :run="run"
    />
    <div v-if="message.metadata?.source_ids?.length" class="chips">
      <button
        v-for="id in message.metadata.source_ids"
        :key="id"
        @click="$emit('select-source', message.metadata?.sources?.find((item) => item.document_id === id) || { document_id: id })"
      >
        来源 {{ id.slice(0, 8) }}
      </button>
    </div>
    <div v-if="message.metadata?.artifact_ids?.length" class="chips">
      <button v-for="id in message.metadata.artifact_ids" :key="id" @click="$emit('select-artifact', id)">
        查看产物
      </button>
    </div>
    <button
      v-if="message.status === 'completed' && !String(message.id).startsWith('legacy-')"
      class="reference"
      @click="$emit('toggle-reference', message)"
    >
      引用此消息
    </button>
    <button
      v-if="message.role === 'user' && ['failed', 'stopped'].includes(run?.status)"
      class="retry"
      @click="$emit('retry', message.id)"
    >
      重试此任务
    </button>
  </article>
</template>

<style scoped>
.message { max-width: 86%; margin: 14px 0; padding: 14px; border: 1px solid var(--border); border-radius: 8px; background: #fff; }
.message.user { margin-left: auto; background: #edf6f2; border-color: #cee3d9; }
.message header { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.message header span { color: var(--muted); font-size: 12px; }
.content { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.65; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.chips button, .retry, .reference { border: 1px solid #cbdad3; border-radius: 999px; padding: 5px 9px; background: #fff; color: #226347; cursor: pointer; }
.retry { margin-top: 10px; border-radius: 5px; }
.reference { margin-top: 10px; border-style: dashed; }
@media (max-width: 760px) { .message { max-width: 96%; } }
</style>
