<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  plan: { type: Array, default: () => [] },
  steps: { type: Array, default: () => [] },
  run: { type: Object, default: null },
  active: Boolean,
})

const expanded = ref(props.active)

watch(
  () => props.active,
  (active) => {
    expanded.value = active
  },
)

const toolLabels = {
  search_knowledge: '检索公共知识库',
  get_document_info: '读取资料信息',
  summarize_document: '整理资料摘要',
  compare_documents: '比较多份资料',
  generate_learning_report: '生成学习报告',
}

const statusLabels = {
  pending: '等待执行',
  running: '正在调用',
  completed: '调用完成',
  failed: '调用失败',
  stopped: '已停止',
}

const toolCount = computed(() => props.steps.length)
const displayedPlan = computed(() => {
  if (props.plan.length) return props.plan
  if (props.steps.length) return ['根据任务选择受控工具，并在每次调用后检查结果']
  return []
})
const durationText = computed(() => {
  const duration = props.steps.reduce(
    (total, step) => total + Number(step.duration_ms || 0),
    0,
  )
  if (!duration) return ''
  if (duration < 1000) return `${duration} 毫秒`
  return `${(duration / 1000).toFixed(duration < 10_000 ? 1 : 0)} 秒`
})

const summaryText = computed(() => {
  if (props.active) return `正在处理 · 已调用 ${toolCount.value} 次工具`
  const prefix = durationText.value ? `已处理 ${durationText.value}` : '处理完成'
  return `${prefix} · ${toolCount.value} 次工具调用`
})

function toolLabel(step) {
  return toolLabels[step.tool_name] || step.tool_name || step.node_name || '受控工具'
}

function decisionText(step, index) {
  if (step.decision_summary) return step.decision_summary
  if (step.status === 'failed') return '工具结果不可用，任务将安全结束。'
  if (step.status === 'stopped') return '任务已停止，不再继续调用工具。'
  if (step.status !== 'completed') return '等待工具返回结果后再决定下一步。'
  if (index < props.steps.length - 1) return '当前信息仍不足，继续选择下一项工具。'
  if (props.active) return '正在检查结果并确定下一步。'
  return '现有结果足以完成任务，已整理为最终回答。'
}
</script>

<template>
  <details
    v-if="plan.length || steps.length || run || active"
    class="run-progress"
    :open="expanded"
    @toggle="expanded = $event.target.open"
  >
    <summary>
      <span class="summary-icon" aria-hidden="true">⌁</span>
      <span>{{ summaryText }}</span>
      <span class="summary-chevron" aria-hidden="true">⌄</span>
    </summary>

    <div class="progress-body">
      <section v-if="displayedPlan.length" class="progress-event plan-event">
        <span class="event-mark">1</span>
        <div>
          <strong>理解任务并制定计划</strong>
          <ol>
            <li v-for="item in displayedPlan" :key="item">{{ item }}</li>
          </ol>
        </div>
      </section>

      <section v-if="!displayedPlan.length && !steps.length" class="progress-event decision-event">
        <span class="event-mark">✓</span>
        <div>
          <strong>{{ active ? '判断任务路由' : '直接回答' }}</strong>
          <p>{{ active ? '正在判断是否需要调用工具。' : '该任务无需调用工具，已直接形成回答。' }}</p>
        </div>
      </section>

      <template v-for="(step, index) in steps" :key="step.id || `${step.sequence}-${index}`">
        <section class="progress-event decision-event">
          <span class="event-mark">●</span>
          <div>
            <strong>选择下一步</strong>
            <p>根据当前任务和已有结果，决定调用“{{ toolLabel(step) }}”。</p>
          </div>
        </section>

        <section class="progress-event tool-event" :class="step.status">
          <span class="event-mark">↗</span>
          <div>
            <div class="event-heading">
              <strong>{{ toolLabel(step) }}</strong>
              <small>{{ statusLabels[step.status] || step.status }}</small>
            </div>
            <p v-if="step.result_summary">{{ step.result_summary }}</p>
            <p v-else-if="step.status === 'running'">工具正在执行，请稍候。</p>
          </div>
        </section>

        <section class="progress-event inspection-event">
          <span class="event-mark">✓</span>
          <div>
            <strong>检查工具结果</strong>
            <p>{{ decisionText(step, index) }}</p>
          </div>
        </section>
      </template>

      <footer v-if="run">
        Token {{ run.used_tokens ?? 0 }}
        <span aria-hidden="true">·</span>
        预估费用 ¥{{ Number(run.estimated_cost_cny || 0).toFixed(4) }}
      </footer>
    </div>
  </details>
</template>

<style scoped>
.run-progress {
  margin: 0 0 10px;
  overflow: hidden;
  border-bottom: 1px solid #e1e8e5;
  color: #52635c;
}
.run-progress summary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 2px 10px;
  list-style: none;
  color: #74847e;
  font-size: 12px;
  cursor: pointer;
}
.run-progress summary::-webkit-details-marker { display: none; }
.summary-icon { color: var(--primary); font-size: 15px; }
.summary-chevron {
  margin-left: auto;
  font-size: 15px;
  transition: transform .2s ease;
}
.run-progress[open] .summary-chevron { transform: rotate(180deg); }
.progress-body {
  display: grid;
  gap: 2px;
  padding: 2px 0 13px 6px;
}
.progress-event {
  position: relative;
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr);
  gap: 9px;
  padding: 7px 0;
}
.progress-event:not(:last-of-type)::after {
  content: "";
  position: absolute;
  top: 28px;
  bottom: -6px;
  left: 10px;
  width: 1px;
  background: #dce6e2;
}
.event-mark {
  position: relative;
  z-index: 1;
  width: 21px;
  height: 21px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  color: #477064;
  background: #edf5f2;
  font-size: 10px;
  font-weight: 800;
}
.tool-event.running .event-mark { animation: pulse 1s infinite alternate; }
.tool-event.failed .event-mark { color: #a33f2f; background: #fff0ed; }
.progress-event strong { color: #355049; font-size: 12px; }
.progress-event p,
.progress-event ol {
  margin: 4px 0 0;
  color: #6f7f79;
  font-size: 12px;
  line-height: 1.6;
}
.progress-event ol { padding-left: 18px; }
.event-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.event-heading small { color: #8b9994; font-size: 11px; }
footer {
  display: flex;
  gap: 7px;
  padding: 8px 0 0 31px;
  color: #91a09d;
  font-size: 10px;
}
@keyframes pulse { to { opacity: .45; transform: scale(.9); } }
</style>
