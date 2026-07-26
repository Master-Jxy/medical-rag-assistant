<script setup>
import { onMounted, ref } from 'vue'
import { getApiErrorMessage } from '../api/http'
import { createMemory, deleteMemory, getMemories, getMemorySettings, getProfile, updateMemorySettings } from '../api/profile'

const profile = ref(null)
const loading = ref(true)
const errorMessage = ref('')
const memoryEnabled = ref(false)
const memories = ref([])
const memoryLabel = ref('')
const memoryContent = ref('')

async function load() {
  loading.value = true
  errorMessage.value = ''
  try {
    const [profileData, setting, memoryData] = await Promise.all([getProfile(), getMemorySettings(), getMemories()])
    profile.value = profileData; memoryEnabled.value = setting.enabled; memories.value = memoryData.items
  }
  catch (error) { errorMessage.value = getApiErrorMessage(error) }
  finally { loading.value = false }
}
async function toggleMemory() { try { memoryEnabled.value = (await updateMemorySettings(!memoryEnabled.value)).enabled } catch (error) { errorMessage.value = getApiErrorMessage(error) } }
async function addMemory() { if (!memoryLabel.value.trim() || !memoryContent.value.trim()) return; try { const item = await createMemory(memoryLabel.value, memoryContent.value); memories.value.unshift(item); memoryLabel.value = ''; memoryContent.value = '' } catch (error) { errorMessage.value = getApiErrorMessage(error) } }
async function removeMemory(id) { if (!window.confirm('确认删除这条记忆？')) return; try { await deleteMemory(id); memories.value = memories.value.filter((item) => item.id !== id) } catch (error) { errorMessage.value = getApiErrorMessage(error) } }
onMounted(load)
</script>

<template>
  <section class="platform-page">
    <header class="page-toolbar"><div><span>ACCOUNT</span><h1>个人中心</h1><p>账号信息以数据库为准。</p></div></header>
    <div v-if="loading" class="state-panel">正在加载账号信息…</div>
    <div v-else-if="errorMessage" class="state-panel error">{{ errorMessage }}</div>
    <dl v-else class="detail-panel">
      <div><dt>显示名称</dt><dd>{{ profile.display_name || '未设置' }}</dd></div>
      <div><dt>邮箱</dt><dd>{{ profile.email }}</dd></div>
      <div><dt>角色</dt><dd><span class="status-badge">{{ profile.role }}</span></dd></div>
      <div><dt>账号状态</dt><dd>{{ profile.is_active ? '正常' : '已停用' }}</dd></div>
      <div><dt>注册时间</dt><dd>{{ new Date(profile.created_at).toLocaleString() }}</dd></div>
    </dl>
    <section v-if="profile" class="memory-panel">
      <header><div><h2>长期记忆</h2><p>默认关闭。只有你主动保存的内容会被使用，可随时删除。</p></div><el-button @click="toggleMemory">{{ memoryEnabled ? '关闭记忆' : '启用记忆' }}</el-button></header>
      <form @submit.prevent="addMemory"><input v-model="memoryLabel" maxlength="100" placeholder="标签，例如：表达偏好"><textarea v-model="memoryContent" maxlength="1000" rows="2" placeholder="不要保存诊断、处方等敏感医疗结论"></textarea><el-button native-type="submit" :disabled="!memoryLabel.trim() || !memoryContent.trim()">保存</el-button></form>
      <div v-if="!memories.length" class="state-panel">暂无主动保存的记忆。</div>
      <article v-for="item in memories" :key="item.id"><div><strong>{{ item.label }}</strong><p>{{ item.content }}</p></div><button @click="removeMemory(item.id)">删除</button></article>
    </section>
  </section>
</template>
<style scoped>
.memory-panel{margin-top:18px;padding:18px;border:1px solid var(--border);border-radius:8px;background:#fff}.memory-panel header{display:flex;justify-content:space-between;gap:16px}.memory-panel h2{margin:0}.memory-panel header p{margin:5px 0;color:var(--muted)}.memory-panel form{display:grid;grid-template-columns:180px 1fr auto;gap:8px;margin:16px 0}.memory-panel input,.memory-panel textarea{padding:9px;border:1px solid var(--border);border-radius:6px;font:inherit}.memory-panel article{display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-top:1px solid var(--border)}.memory-panel article p{margin:4px 0}.memory-panel article button{border:0;background:none;color:#a33;cursor:pointer}@media(max-width:700px){.memory-panel form{grid-template-columns:1fr}.memory-panel header{align-items:flex-start;flex-direction:column}}
</style>
