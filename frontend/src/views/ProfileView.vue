<script setup>
import { onMounted, ref } from 'vue'
import { getProfile } from '../api/profile'
import { getApiErrorMessage } from '../api/http'
import MemoryCenter from '../features/profile/MemoryCenter.vue'
import UsageCenter from '../features/profile/UsageCenter.vue'

const profile = ref(null), loading = ref(true), errorMessage = ref('')
async function load() {
  try { profile.value = await getProfile() }
  catch (error) { errorMessage.value = getApiErrorMessage(error) }
  finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <section class="platform-page">
    <header class="page-toolbar"><div><span>ACCOUNT</span><h1>个人中心</h1><p>账号、长期记忆和用量都以服务端数据为准。</p></div></header>
    <div v-if="errorMessage" class="state-panel error" role="alert">{{ errorMessage }}</div>
    <div v-if="loading" class="state-panel">正在加载账号信息…</div>
    <template v-else-if="profile">
      <dl class="detail-panel">
        <div><dt>显示名称</dt><dd>{{ profile.display_name || '未设置' }}</dd></div>
        <div><dt>邮箱</dt><dd>{{ profile.email }}</dd></div>
        <div><dt>角色</dt><dd><span class="status-badge">{{ profile.role }}</span></dd></div>
        <div><dt>账号状态</dt><dd>{{ profile.is_active ? '正常' : '已停用' }}</dd></div>
      </dl>
      <MemoryCenter @error="errorMessage = $event" />
      <UsageCenter @error="errorMessage = $event" />
    </template>
  </section>
</template>
