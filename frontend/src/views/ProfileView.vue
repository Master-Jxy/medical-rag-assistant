<script setup>
import { onMounted, ref } from 'vue'
import { getApiErrorMessage } from '../api/http'
import { getProfile } from '../api/profile'

const profile = ref(null)
const loading = ref(true)
const errorMessage = ref('')

async function load() {
  loading.value = true
  errorMessage.value = ''
  try { profile.value = await getProfile() }
  catch (error) { errorMessage.value = getApiErrorMessage(error) }
  finally { loading.value = false }
}
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
  </section>
</template>
