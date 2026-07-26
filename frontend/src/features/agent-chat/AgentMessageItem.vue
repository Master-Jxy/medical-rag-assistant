<script setup>
import { computed, ref } from 'vue'
import AgentRunProgress from './AgentRunProgress.vue'

const props = defineProps({
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

const sourcesExpanded = ref(false)
const artifactsExpanded = ref(false)

const isAssistant = computed(() => props.message.role === 'assistant')
const isActive = computed(() => ['streaming', 'pending'].includes(props.message.status))
const content = computed(() => props.message.content || props.live?.output || '')
const steps = computed(
  () => props.message.parts?.steps?.length
    ? props.message.parts.steps
    : props.live?.steps || props.run?.steps || [],
)
const plan = computed(
  () => props.message.parts?.plan?.length
    ? props.message.parts.plan
    : props.live?.plan || [],
)
const sources = computed(() => {
  if (props.message.parts?.sources?.length) return props.message.parts.sources
  return (props.message.metadata?.source_ids || []).map((document_id) => ({ document_id }))
})
const artifacts = computed(() => {
  if (props.message.parts?.artifacts?.length) return props.message.parts.artifacts
  return (props.message.metadata?.artifact_ids || []).map((id) => ({ id }))
})
</script>

<template>
  <article class="message-row" :class="message.role">
    <div class="avatar">{{ message.role === 'user' ? '你' : 'M' }}</div>
    <div class="message-body">
      <span class="role-name">{{ message.role === 'user' ? '我的问题' : '资料 Agent' }}</span>

      <AgentRunProgress
        v-if="isAssistant && (plan.length || steps.length || run || isActive)"
        :plan="plan"
        :steps="steps"
        :run="run"
        :status="message.status"
        :active="isActive"
      />

      <div
        v-if="content || isActive"
        class="bubble"
        :class="{ thinking: isActive && !content, failed: message.status === 'failed' }"
      >
        <template v-if="content">
          {{ content }}<i v-if="isActive" class="stream-cursor"></i>
        </template>
        <template v-else>
          <i></i><i></i><i></i><span>正在理解任务并准备下一步</span>
        </template>
      </div>

      <div v-if="sources.length" class="sources">
        <button
          type="button"
          class="parts-toggle"
          :aria-expanded="sourcesExpanded ? 'true' : 'false'"
          @click="sourcesExpanded = !sourcesExpanded"
        >
          <span>引用来源 · {{ sources.length }}</span>
          <i :class="{ expanded: sourcesExpanded }">⌄</i>
        </button>
        <div v-if="sourcesExpanded" class="parts-list">
          <details
            v-for="source in sources"
            :key="`${source.document_id}-${source.chunk_id || ''}-${source.page || ''}`"
          >
            <summary>
              <span>{{ source.file_name || '已发布资料' }}</span>
              <small>{{ source.page ? `第 ${source.page} 页` : '文本资料' }}</small>
            </summary>
            <p v-if="source.content">{{ source.content }}</p>
            <div class="part-actions">
              <button @click="$emit('select-source', source)">查看来源</button>
              <button @click="$emit('toggle-source-reference', source)">引用到下一轮</button>
            </div>
          </details>
        </div>
      </div>

      <div v-if="artifacts.length" class="artifacts">
        <button
          type="button"
          class="parts-toggle"
          :aria-expanded="artifactsExpanded ? 'true' : 'false'"
          @click="artifactsExpanded = !artifactsExpanded"
        >
          <span>生成产物 · {{ artifacts.length }}</span>
          <i :class="{ expanded: artifactsExpanded }">⌄</i>
        </button>
        <div v-if="artifactsExpanded" class="parts-list">
          <div v-for="artifact in artifacts" :key="artifact.id || artifact.artifact_id" class="artifact-row">
            <button @click="$emit('select-artifact', artifact)">
              {{ artifact.file_name || '查看生成产物' }}
            </button>
            <button @click="$emit('toggle-artifact-reference', artifact)">引用到下一轮</button>
          </div>
        </div>
      </div>

      <div class="message-actions">
        <button
          v-if="message.status === 'completed'"
          @click="$emit('toggle-reference', message)"
        >
          引用此消息
        </button>
        <button
          v-if="message.role === 'user' && ['failed', 'stopped'].includes(run?.status)"
          @click="$emit('retry', message.id)"
        >
          重试此任务
        </button>
      </div>
    </div>
  </article>
</template>

<style scoped>
.message-row { display: flex; gap: 13px; margin-bottom: 28px; }
.message-row.user { flex-direction: row-reverse; }
.avatar {
  flex: 0 0 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: 11px;
  color: #fff;
  background: var(--primary);
  font-size: 13px;
  font-weight: 800;
}
.user .avatar { color: var(--ink); background: #e6eeeb; }
.message-body { width: min(78%, 760px); min-width: 0; }
.user .message-body { text-align: right; }
.role-name {
  display: block;
  margin: 0 4px 7px;
  color: var(--muted);
  font-size: 11px;
}
.bubble {
  padding: 15px 17px;
  border-radius: 6px 17px 17px 17px;
  color: #29433e;
  background: #f1f6f4;
  line-height: 1.75;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  text-align: left;
}
.bubble.failed { color: #8c3e31; background: #fff3f0; }
.user .bubble {
  color: #fff;
  background: var(--primary);
  border-radius: 17px 6px 17px 17px;
}
.sources, .artifacts { margin-top: 12px; text-align: left; }
.parts-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 3px 0 8px;
  border: 0;
  color: var(--muted);
  background: transparent;
  font: inherit;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.parts-toggle i { font-style: normal; font-size: 16px; transition: transform .2s ease; }
.parts-toggle i.expanded { transform: rotate(180deg); }
.parts-list details {
  margin-top: 7px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: #fff;
}
.parts-list summary {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 11px 13px;
  color: var(--ink);
  font-size: 13px;
  cursor: pointer;
}
.parts-list summary small { color: var(--muted); white-space: nowrap; }
.parts-list p {
  margin: 0;
  padding: 0 13px 10px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.7;
}
.part-actions, .artifact-row {
  display: flex;
  gap: 10px;
  padding: 0 13px 11px;
}
.artifact-row {
  align-items: center;
  justify-content: space-between;
  margin-top: 7px;
  padding: 11px 13px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: #fff;
}
.part-actions button, .artifact-row button, .message-actions button {
  padding: 0;
  border: 0;
  color: var(--primary);
  background: transparent;
  font-size: 12px;
  cursor: pointer;
}
.message-actions { display: flex; gap: 12px; margin-top: 9px; }
.user .message-actions { justify-content: flex-end; }
.message-actions button { color: #81908b; }
.thinking { display: flex; align-items: center; gap: 5px; color: var(--muted); }
.thinking > i:not(.stream-cursor) {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--primary);
  animation: pulse 1.1s infinite alternate;
}
.thinking > i:nth-child(2) { animation-delay: .2s; }
.thinking > i:nth-child(3) { animation-delay: .4s; }
.thinking span { margin-left: 5px; font-size: 13px; }
.stream-cursor {
  display: inline-block;
  width: 2px;
  height: 1em;
  margin-left: 3px;
  vertical-align: -2px;
  background: var(--primary);
  animation: blink .8s infinite;
}
@keyframes pulse { to { opacity: .25; transform: translateY(-2px); } }
@keyframes blink { 50% { opacity: 0; } }
@media (max-width: 760px) {
  .message-body { width: calc(100% - 47px); }
}
</style>
