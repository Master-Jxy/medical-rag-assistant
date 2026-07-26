<script setup>
import AgentRunProgress from './AgentRunProgress.vue'

defineProps({
  message: { type: Object, required: true },
  run: { type: Object, default: null },
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
</script>

<template>
  <article class="message" :class="message.role">
    <header>
      <strong>{{ message.role === 'user' ? '你' : '资料 Agent' }}</strong>
      <span v-if="['streaming', 'pending'].includes(message.status)">正在处理</span>
      <span v-else-if="message.status === 'failed'">失败</span>
      <span v-else-if="message.status === 'stopped'">已停止</span>
    </header>
    <div class="content">{{ message.content || live?.output || '正在处理…' }}</div>
    <AgentRunProgress
      v-if="message.role === 'assistant'"
      :plan="message.parts?.plan || live?.plan || []"
      :steps="message.parts?.steps || live?.steps || run?.steps || []"
      :run="run"
    />
    <div v-if="message.parts?.sources?.length || message.metadata?.source_ids?.length" class="message-parts">
      <strong>引用来源</strong>
      <template
        v-for="source in (message.parts?.sources?.length ? message.parts.sources : message.metadata.source_ids.map((document_id) => ({ document_id })))"
        :key="`${source.document_id}-${source.chunk_id || ''}-${source.page || ''}`"
      >
        <button @click="$emit('select-source', source)">
          {{ source.file_name || '已发布资料' }}<template v-if="source.page"> · 第{{ source.page }}页</template>
        </button>
        <button @click="$emit('toggle-source-reference', source)">引用</button>
      </template>
    </div>
    <div v-if="message.parts?.artifacts?.length || message.metadata?.artifact_ids?.length" class="message-parts">
      <strong>产物</strong>
      <template
        v-for="artifact in (message.parts?.artifacts?.length ? message.parts.artifacts : message.metadata.artifact_ids.map((id) => ({ id })))"
        :key="artifact.id || artifact.artifact_id"
      >
        <button @click="$emit('select-artifact', artifact)">
          {{ artifact.file_name || '查看产物' }}
        </button>
        <button @click="$emit('toggle-artifact-reference', artifact)">引用</button>
      </template>
    </div>
    <button
      v-if="message.status === 'completed'"
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
.message-parts { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 10px; }
.message-parts > strong { width: 100%; color: #52635c; font-size: 12px; }
.message-parts button, .retry, .reference { border: 1px solid #cbdad3; border-radius: 999px; padding: 5px 9px; background: #fff; color: #226347; cursor: pointer; }
.retry { margin-top: 10px; border-radius: 5px; }
.reference { margin-top: 10px; border-style: dashed; }
@media (max-width: 760px) { .message { max-width: 96%; } }
</style>
