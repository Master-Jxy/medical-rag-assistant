<script setup>
import { onMounted, ref } from 'vue'
import { BrainCircuit, Check, Plus, Sparkles, Trash2, X } from '@lucide/vue'

import ConfirmDialog from '../../components/ConfirmDialog.vue'
import { approveMemory, createMemory, deleteMemory, getMemories, getMemorySettings, rejectMemory, updateMemorySettings } from '../../api/profile'
import { getApiErrorMessage } from '../../api/http'

const emit = defineEmits(['error'])
const memoryEnabled = ref(false)
const autoExtractEnabled = ref(false)
const memories = ref([])
const label = ref('')
const content = ref('')
const loading = ref(true)
const savingSettings = ref(false)
const adding = ref(false)
const deleteTarget = ref(null)
const deleting = ref(false)

const statusLabels = { active: '已生效', candidate: '待确认', rejected: '已拒绝' }

async function load() {
  loading.value = true
  try {
    const [settings, data] = await Promise.all([getMemorySettings(), getMemories()])
    memoryEnabled.value = settings.enabled
    autoExtractEnabled.value = settings.auto_extract_enabled
    memories.value = data.items || []
  } catch (error) {
    emit('error', getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function saveSettings(enabled = memoryEnabled.value, auto = autoExtractEnabled.value) {
  if (savingSettings.value) return
  savingSettings.value = true
  try {
    const result = await updateMemorySettings(enabled, auto)
    memoryEnabled.value = result.enabled
    autoExtractEnabled.value = result.auto_extract_enabled
  } catch (error) {
    emit('error', getApiErrorMessage(error))
  } finally {
    savingSettings.value = false
  }
}

async function add() {
  if (!label.value.trim() || !content.value.trim() || adding.value) return
  adding.value = true
  try {
    memories.value.unshift(await createMemory(label.value, content.value))
    label.value = ''
    content.value = ''
  } catch (error) {
    emit('error', getApiErrorMessage(error))
  } finally {
    adding.value = false
  }
}

async function transition(id, action) {
  try {
    const changed = action === 'approve' ? await approveMemory(id) : await rejectMemory(id)
    memories.value = memories.value.map((item) => item.id === id ? changed : item)
  } catch (error) {
    emit('error', getApiErrorMessage(error))
  }
}

async function remove() {
  if (!deleteTarget.value || deleting.value) return
  deleting.value = true
  try {
    await deleteMemory(deleteTarget.value.id)
    memories.value = memories.value.filter((item) => item.id !== deleteTarget.value.id)
    deleteTarget.value = null
  } catch (error) {
    emit('error', getApiErrorMessage(error))
  } finally {
    deleting.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="memory-panel">
    <header class="panel-header">
      <div><h2>长期记忆</h2><p>经你确认的个人信息可辅助 RAG 与 Agent 理解后续问题。</p></div>
      <label class="switch-control">
        <input :checked="memoryEnabled" type="checkbox" :disabled="savingSettings" @change="saveSettings(!memoryEnabled, false)" />
        <span aria-hidden="true"></span><b>{{ memoryEnabled ? '已启用' : '已关闭' }}</b>
      </label>
    </header>

    <div v-if="loading" class="memory-state">正在加载长期记忆…</div>
    <template v-else>
      <section class="memory-settings">
        <div><span><Sparkles :size="17" /></span><div><strong>自动整理候选记忆</strong><p>模型只会生成候选项，敏感健康信息仍需你确认后才会生效。</p></div></div>
        <label class="switch-control compact"><input v-model="autoExtractEnabled" type="checkbox" :disabled="!memoryEnabled || savingSettings" @change="saveSettings()" /><span aria-hidden="true"></span></label>
      </section>

      <form class="memory-form" @submit.prevent="add">
        <div class="form-heading"><div><Plus :size="16" /><strong>手动添加记忆</strong></div><small>最多 1,000 字</small></div>
        <div class="form-fields">
          <label><span>标签</span><input v-model="label" maxlength="100" placeholder="例如：饮食偏好" /></label>
          <label><span>内容</span><textarea v-model="content" maxlength="1000" rows="3" placeholder="记录希望助手长期记住的信息"></textarea></label>
        </div>
        <footer><button class="primary-action" type="submit" :disabled="adding || !label.trim() || !content.trim()">{{ adding ? '保存中…' : '保存记忆' }}</button></footer>
      </form>

      <section class="memory-list">
        <header><div><BrainCircuit :size="17" /><h3>记忆条目</h3></div><span>{{ memories.length }} 条</span></header>
        <div v-if="!memories.length" class="memory-state"><BrainCircuit :size="23" /><strong>暂无长期记忆</strong><p>你可以手动添加，也可以启用自动整理。</p></div>
        <article v-for="item in memories" :key="item.id">
          <div class="memory-copy"><div><strong>{{ item.label }}</strong><span class="status-badge" :data-status="item.status === 'active' ? 'ready' : item.status">{{ statusLabels[item.status] || item.status }}</span></div><p>{{ item.content }}</p></div>
          <div class="memory-actions">
            <button v-if="item.status === 'candidate'" class="icon-action approve" type="button" title="确认记忆" @click="transition(item.id, 'approve')"><Check :size="15" /></button>
            <button v-if="item.status === 'candidate'" class="icon-action" type="button" title="拒绝候选" @click="transition(item.id, 'reject')"><X :size="15" /></button>
            <button class="icon-action danger" type="button" title="删除记忆" @click="deleteTarget = item"><Trash2 :size="15" /></button>
          </div>
        </article>
      </section>
    </template>

    <ConfirmDialog
      :open="Boolean(deleteTarget)"
      title="删除这条长期记忆？"
      :description="deleteTarget ? `“${deleteTarget.label}”删除后将不再参与后续问答。` : ''"
      confirm-text="确认删除"
      :loading="deleting"
      @cancel="deleteTarget = null"
      @confirm="remove"
    />
  </section>
</template>

<style scoped>
.memory-panel { border: 1px solid var(--border-default); border-radius: 8px; background: var(--bg-surface); }
.panel-header { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 16px; border-bottom: 1px solid var(--border-default); }
.panel-header h2 { margin: 0; color: var(--text-strong); font-size: 15px; }
.panel-header p { margin: 4px 0 0; color: var(--text-muted); font-size: 11px; line-height: 17px; }
.switch-control { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; }
.switch-control input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.switch-control > span { position: relative; width: 34px; height: 19px; flex: 0 0 34px; border-radius: 10px; background: #b8c2bf; transition: background .16s ease; }
.switch-control > span::after { content: ''; position: absolute; top: 3px; left: 3px; width: 13px; height: 13px; border-radius: 50%; background: #fff; transition: transform .16s ease; }
.switch-control input:checked + span { background: var(--brand); }
.switch-control input:checked + span::after { transform: translateX(15px); }
.switch-control b { color: var(--text-default); font-size: 11px; font-weight: 600; }
.memory-settings { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin: 16px; padding: 12px; border: 1px solid #cbded9; border-radius: 7px; background: #f5faf8; }
.memory-settings > div { display: flex; align-items: flex-start; gap: 10px; }
.memory-settings > div > span { width: 31px; height: 31px; flex: 0 0 31px; display: grid; place-items: center; border-radius: 6px; color: var(--brand); background: #e2f1ec; }
.memory-settings strong { color: var(--text-strong); font-size: 12px; }
.memory-settings p { margin: 3px 0 0; color: var(--text-muted); font-size: 11px; line-height: 17px; }
.memory-form { margin: 0 16px 16px; padding: 14px; border: 1px solid var(--border-default); border-radius: 7px; }
.form-heading { display: flex; justify-content: space-between; gap: 14px; margin-bottom: 12px; }
.form-heading > div { display: flex; align-items: center; gap: 7px; color: var(--brand); }
.form-heading strong { color: var(--text-strong); font-size: 13px; }
.form-heading small { color: var(--text-muted); font-size: 10px; }
.form-fields { display: grid; grid-template-columns: minmax(130px, .35fr) minmax(0, 1fr); gap: 10px; }
.form-fields label { display: grid; gap: 6px; color: var(--text-muted); font-size: 11px; }
.form-fields input, .form-fields textarea { width: 100%; padding: 9px 10px; border: 1px solid var(--border-strong); border-radius: 6px; outline: 0; color: var(--text-strong); background: #fff; resize: vertical; }
.form-fields input:focus, .form-fields textarea:focus { border-color: var(--action); box-shadow: 0 0 0 3px rgba(37,99,235,.09); }
.memory-form footer { display: flex; justify-content: flex-end; margin-top: 10px; }
.primary-action { min-height: 34px; padding: 0 12px; border: 0; border-radius: 6px; color: #fff; background: var(--action); cursor: pointer; font-size: 12px; }
.primary-action:disabled { cursor: wait; opacity: .55; }
.memory-list { border-top: 1px solid var(--border-default); }
.memory-list > header { min-height: 48px; display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 0 16px; }
.memory-list > header > div { display: flex; align-items: center; gap: 8px; color: var(--brand); }
.memory-list h3 { margin: 0; color: var(--text-strong); font-size: 13px; }
.memory-list > header > span { color: var(--text-muted); font-size: 11px; }
.memory-list article { min-height: 66px; display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 12px 16px; border-top: 1px solid #edf1f0; }
.memory-copy { min-width: 0; }
.memory-copy > div { display: flex; align-items: center; gap: 7px; }
.memory-copy strong { color: var(--text-strong); font-size: 12px; }
.memory-copy p { margin: 5px 0 0; color: var(--text-muted); font-size: 11px; line-height: 18px; overflow-wrap: anywhere; }
.memory-actions { display: flex; gap: 4px; }
.icon-action { width: 30px; height: 30px; display: grid; place-items: center; padding: 0; border: 1px solid var(--border-default); border-radius: 6px; color: var(--text-muted); background: #fff; cursor: pointer; }
.icon-action.approve { color: var(--success); }
.icon-action.danger { color: var(--danger); }
.memory-state { min-height: 170px; display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 7px; padding: 24px; color: var(--text-muted); text-align: center; }
.memory-state strong { color: var(--text-strong); font-size: 13px; }
.memory-state p { margin: 0; font-size: 11px; }
@media (max-width: 700px) { .panel-header { align-items: flex-start; flex-direction: column; } .form-fields { grid-template-columns: 1fr; } .memory-settings { align-items: flex-start; } .memory-list article { align-items: flex-start; flex-direction: column; } }
</style>
