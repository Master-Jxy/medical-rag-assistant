<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  createAgentRun,
  downloadAgentArtifact,
  getAgentRun,
  listAgentRuns,
  stopAgentRun,
  streamAgentRun,
} from '../api/agent.js'
import { getApiErrorMessage } from '../api/http.js'

const task = ref('')
const runs = ref([])
const selected = ref(null)
const livePlan = ref([])
const liveSteps = ref([])
const liveOutput = ref('')
const loading = ref(true)
const running = ref(false)
const errorMessage = ref('')
const notice = ref('')
const downloadingId = ref('')

const canSubmit = computed(() => task.value.trim() && !running.value)
const statusLabel = {
  pending: '待执行',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  stopped: '已停止',
}

async function loadRuns(selectFirst = false) {
  const result = await listAgentRuns()
  runs.value = result.items
  if (selectFirst && runs.value.length) await selectRun(runs.value[0].id)
}

async function selectRun(id) {
  selected.value = await getAgentRun(id)
  livePlan.value = []
  liveSteps.value = selected.value.steps || []
  liveOutput.value = selected.value.final_result || ''
}

function handleEvent(event, data) {
  if (event === 'plan_ready') livePlan.value = data.plan || []
  if (event === 'tool_started') {
    liveSteps.value.push({
      id: `live-${data.step}`,
      sequence: data.step,
      tool_name: data.tool_name,
      status: 'running',
      result_summary: null,
    })
  }
  if (event === 'tool_completed') {
    const step = liveSteps.value.findLast((item) => item.tool_name === data.tool_name)
    if (step) {
      step.status = data.status
      step.result_summary = data.summary
    }
  }
  if (event === 'token') liveOutput.value += data.content || ''
  if (event === 'stopped') notice.value = '运行已安全停止。'
}

async function submit() {
  const value = task.value.trim()
  if (!value || running.value) return
  running.value = true
  errorMessage.value = ''
  notice.value = ''
  livePlan.value = []
  liveSteps.value = []
  liveOutput.value = ''
  try {
    const run = await createAgentRun(value)
    selected.value = run
    task.value = ''
    await streamAgentRun(run.id, { onEvent: handleEvent })
    selected.value = await getAgentRun(run.id)
    liveSteps.value = selected.value.steps || []
    liveOutput.value = selected.value.final_result || liveOutput.value
    await loadRuns()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
    if (selected.value?.id) {
      try {
        selected.value = await getAgentRun(selected.value.id)
      } catch {
        // 保留已有可见状态。
      }
    }
  } finally {
    running.value = false
  }
}

async function stop() {
  if (!selected.value?.id || !running.value) return
  try {
    const result = await stopAgentRun(selected.value.id)
    notice.value = result.message
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  }
}

async function download(artifact) {
  downloadingId.value = artifact.id
  errorMessage.value = ''
  try {
    const blob = await downloadAgentArtifact(artifact.id)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = artifact.file_name
    anchor.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    downloadingId.value = ''
  }
}

onMounted(async () => {
  try {
    await loadRuns(true)
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <section class="agent-page">
    <header class="page-toolbar">
      <div>
        <span>CONTROLLED AGENT</span>
        <h1>资料整理 Agent</h1>
        <p>只读取已发布公共知识，最多执行 5 步；不会诊断、开处方或执行系统命令。</p>
      </div>
    </header>

    <div v-if="errorMessage" class="state-panel error">{{ errorMessage }}</div>
    <div v-if="notice" class="state-panel success">{{ notice }}</div>

    <form class="agent-composer" @submit.prevent="submit">
      <label for="agent-task">整理任务</label>
      <textarea
        id="agent-task"
        v-model="task"
        maxlength="4000"
        rows="4"
        placeholder="例如：比较两份患者安全资料的适用范围，并生成学习报告"
      />
      <div>
        <small>{{ task.length }}/4000</small>
        <el-button v-if="running" type="danger" @click="stop">停止运行</el-button>
        <el-button type="primary" native-type="submit" :disabled="!canSubmit" :loading="running">
          开始整理
        </el-button>
      </div>
    </form>

    <div class="agent-layout">
      <aside class="run-panel">
        <div class="panel-title"><h2>运行历史</h2><button @click="loadRuns()">刷新</button></div>
        <div v-if="loading" class="empty-state">正在加载…</div>
        <div v-else-if="!runs.length" class="empty-state">暂无运行记录。</div>
        <button
          v-for="run in runs"
          :key="run.id"
          class="run-item"
          :class="{ active: selected?.id === run.id }"
          @click="selectRun(run.id)"
        >
          <strong>{{ run.task }}</strong>
          <span>{{ statusLabel[run.status] || run.status }} · {{ run.step_count }}/{{ run.max_steps }} 步</span>
        </button>
      </aside>

      <article class="run-detail">
        <div v-if="!selected" class="empty-state">选择历史运行，或创建一项新任务。</div>
        <template v-else>
          <header>
            <div><small>当前任务</small><h2>{{ selected.task }}</h2></div>
            <span class="status-badge">{{ statusLabel[selected.status] || selected.status }}</span>
          </header>

          <section v-if="livePlan.length" class="detail-section">
            <h3>执行计划</h3>
            <ol><li v-for="item in livePlan" :key="item">{{ item }}</li></ol>
          </section>

          <section class="detail-section">
            <h3>步骤时间线</h3>
            <div v-if="!liveSteps.length" class="empty-state compact">尚未执行工具。</div>
            <div v-for="step in liveSteps" :key="step.id" class="timeline-item">
              <i />
              <div>
                <strong>第 {{ step.sequence }} 步 · {{ step.tool_name || step.node_name }}</strong>
                <span>{{ statusLabel[step.status] || step.status }}</span>
                <p v-if="step.result_summary">{{ step.result_summary }}</p>
              </div>
            </div>
          </section>

          <section v-if="liveOutput" class="detail-section">
            <h3>最终结果</h3>
            <pre>{{ liveOutput }}</pre>
          </section>

          <section v-if="selected.artifacts?.length" class="detail-section">
            <h3>可下载产物</h3>
            <button
              v-for="artifact in selected.artifacts"
              :key="artifact.id"
              class="artifact-link"
              :disabled="downloadingId === artifact.id"
              @click="download(artifact)"
            >
              {{ downloadingId === artifact.id ? '正在下载…' : artifact.file_name }}
            </button>
          </section>

          <footer>
            Token：{{ selected.used_tokens ?? 0 }} · 预估费用：¥{{ Number(selected.estimated_cost_cny || 0).toFixed(4) }}
          </footer>
        </template>
      </article>
    </div>
  </section>
</template>

<style scoped>
.agent-page { min-width: 0; }
.agent-composer, .run-panel, .run-detail { border: 1px solid var(--border); background: #fff; border-radius: 8px; }
.agent-composer { margin: 18px 0; padding: 18px; }
.agent-composer label { display: block; margin-bottom: 8px; font-weight: 700; }
.agent-composer textarea { width: 100%; resize: vertical; border: 1px solid var(--border); border-radius: 6px; padding: 12px; font: inherit; box-sizing: border-box; }
.agent-composer > div { display: flex; justify-content: flex-end; align-items: center; gap: 10px; margin-top: 10px; }
.agent-composer small { margin-right: auto; color: var(--muted); }
.agent-layout { display: grid; grid-template-columns: minmax(220px, 300px) minmax(0, 1fr); gap: 16px; }
.run-panel { padding: 12px; align-self: start; max-height: 620px; overflow: auto; }
.panel-title, .run-detail > header { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.panel-title h2, .run-detail h2 { margin: 0; font-size: 17px; }
.panel-title button { border: 0; background: none; color: var(--primary); cursor: pointer; }
.run-item { width: 100%; text-align: left; display: grid; gap: 5px; margin-top: 8px; padding: 11px; border: 1px solid transparent; border-radius: 6px; background: #f7f9f8; cursor: pointer; }
.run-item.active { border-color: var(--primary); background: #f1f8f5; }
.run-item strong { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.run-item span, .run-detail small, .run-detail footer { color: var(--muted); font-size: 12px; }
.run-detail { min-height: 420px; padding: 18px; }
.run-detail > header { padding-bottom: 14px; border-bottom: 1px solid var(--border); }
.detail-section { margin-top: 18px; }
.detail-section h3 { margin: 0 0 10px; font-size: 14px; }
.detail-section ol { margin: 0; padding-left: 22px; }
.timeline-item { display: grid; grid-template-columns: 10px 1fr; gap: 10px; margin: 12px 0; }
.timeline-item i { width: 8px; height: 8px; margin-top: 6px; border-radius: 50%; background: var(--primary); }
.timeline-item div { display: grid; gap: 4px; }
.timeline-item span { color: var(--muted); font-size: 12px; }
.timeline-item p { margin: 2px 0 0; color: #46534f; }
.detail-section pre { margin: 0; padding: 14px; white-space: pre-wrap; overflow-wrap: anywhere; background: #f7f9f8; border-radius: 6px; font: inherit; line-height: 1.65; }
.artifact-link { display: block; margin: 8px 0; padding: 0; border: 0; background: none; color: var(--primary); cursor: pointer; }
.run-detail footer { margin-top: 20px; padding-top: 12px; border-top: 1px solid var(--border); }
.empty-state { padding: 24px 8px; text-align: center; color: var(--muted); }
.empty-state.compact { padding: 10px 0; text-align: left; }
@media (max-width: 760px) {
  .agent-layout { grid-template-columns: 1fr; }
  .run-panel { max-height: 280px; }
  .agent-composer > div { flex-wrap: wrap; }
}
</style>
