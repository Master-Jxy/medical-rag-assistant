<script setup>
import { onMounted, ref } from 'vue'
import { approveMemory, createMemory, deleteMemory, getMemories, getMemorySettings, rejectMemory, updateMemorySettings } from '../../api/profile'
import { getApiErrorMessage } from '../../api/http'

const emit = defineEmits(['error'])
const memoryEnabled = ref(false), autoExtractEnabled = ref(false), memories = ref([])
const label = ref(''), content = ref(''), loading = ref(true)
async function load() {
  try {
    const [settings, data] = await Promise.all([getMemorySettings(), getMemories()])
    memoryEnabled.value = settings.enabled; autoExtractEnabled.value = settings.auto_extract_enabled
    memories.value = data.items || []
  } catch (error) { emit('error', getApiErrorMessage(error)) } finally { loading.value = false }
}
async function saveSettings(enabled = memoryEnabled.value, auto = autoExtractEnabled.value) {
  try {
    const result = await updateMemorySettings(enabled, auto)
    memoryEnabled.value = result.enabled; autoExtractEnabled.value = result.auto_extract_enabled
  } catch (error) { emit('error', getApiErrorMessage(error)) }
}
async function add() {
  if (!label.value.trim() || !content.value.trim()) return
  try {
    memories.value.unshift(await createMemory(label.value, content.value))
    label.value = ''; content.value = ''
  } catch (error) { emit('error', getApiErrorMessage(error)) }
}
async function transition(id, action) {
  try {
    const changed = action === 'approve' ? await approveMemory(id) : await rejectMemory(id)
    memories.value = memories.value.map((item) => item.id === id ? changed : item)
  } catch (error) { emit('error', getApiErrorMessage(error)) }
}
async function remove(id) {
  if (!window.confirm('确认删除这条记忆？')) return
  try { await deleteMemory(id); memories.value = memories.value.filter((item) => item.id !== id) }
  catch (error) { emit('error', getApiErrorMessage(error)) }
}
onMounted(load)
</script>

<template>
  <section class="panel">
    <header><div><h2>长期记忆</h2><p>健康背景等敏感候选必须由你确认后才会生效。</p></div><el-button @click="saveSettings(!memoryEnabled, false)">{{ memoryEnabled ? '关闭并保留' : '启用记忆' }}</el-button></header>
    <div v-if="loading" class="state-panel">正在加载长期记忆…</div>
    <template v-else>
      <label class="setting"><input v-model="autoExtractEnabled" type="checkbox" :disabled="!memoryEnabled" @change="saveSettings()"> 自动整理低风险候选</label>
      <form @submit.prevent="add"><input v-model="label" maxlength="100" aria-label="记忆标签" placeholder="标签"><textarea v-model="content" maxlength="1000" rows="2" aria-label="记忆内容" placeholder="记忆内容"></textarea><el-button native-type="submit" :disabled="!label.trim() || !content.trim()">保存</el-button></form>
      <div v-if="!memories.length" class="state-panel">暂无长期记忆。</div>
      <article v-for="item in memories" :key="item.id"><div><strong>{{ item.label }}</strong> <span class="status-badge">{{ item.status }}</span><p>{{ item.content }}</p></div><div class="actions"><button v-if="item.status === 'candidate'" @click="transition(item.id, 'approve')">确认</button><button v-if="item.status === 'candidate'" @click="transition(item.id, 'reject')">拒绝</button><button @click="remove(item.id)">删除</button></div></article>
    </template>
  </section>
</template>

<style scoped>
.panel{margin-top:18px;padding:18px;border:1px solid var(--border);border-radius:8px;background:#fff}.panel header{display:flex;justify-content:space-between;gap:16px}.panel h2{margin:0}.panel header p{margin:5px 0;color:var(--muted)}.setting{display:flex;gap:8px;margin-top:12px}.panel form{display:grid;grid-template-columns:180px 1fr auto;gap:8px;margin:16px 0}.panel input,.panel textarea{padding:9px;border:1px solid var(--border);border-radius:6px;font:inherit}.panel article{display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-top:1px solid var(--border)}.panel article p{margin:4px 0}.actions{display:flex;gap:4px}.actions button{border:0;background:none;color:#963b32;cursor:pointer}@media(max-width:700px){.panel form{grid-template-columns:1fr}.panel header{align-items:flex-start;flex-direction:column}.panel article{align-items:flex-start;flex-direction:column}}
</style>
