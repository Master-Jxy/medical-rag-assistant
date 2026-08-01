<script setup>
import { computed, onMounted, ref } from 'vue'
import { BrainCircuit, CheckCircle2, CircleUserRound, Mail, ShieldCheck, UserRound, WalletCards } from '@lucide/vue'

import { getProfile } from '../api/profile'
import { getApiErrorMessage } from '../api/http'
import MemoryCenter from '../features/profile/MemoryCenter.vue'
import UsageCenter from '../features/profile/UsageCenter.vue'

const profile = ref(null)
const loading = ref(true)
const errorMessage = ref('')
const activeTab = ref('usage')

const initials = computed(() => (profile.value?.display_name || profile.value?.email || 'U').slice(0, 1).toUpperCase())
const roleLabel = computed(() => ({ user: '普通用户', admin: '管理员', super_admin: '超级管理员' }[profile.value?.role] || profile.value?.role))

const tabs = [
  { id: 'usage', label: '用量与额度', icon: WalletCards },
  { id: 'account', label: '账号信息', icon: CircleUserRound },
  { id: 'memory', label: '长期记忆', icon: BrainCircuit },
]

async function load() {
  loading.value = true
  errorMessage.value = ''
  try {
    profile.value = await getProfile()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="platform-page profile-page">
    <header class="page-toolbar"><div><span>ACCOUNT CENTER</span><h1>个人中心</h1><p>管理账号资料、长期记忆与模型调用额度。</p></div></header>
    <div v-if="errorMessage" class="state-panel error" role="alert">{{ errorMessage }}</div>
    <div v-if="loading" class="state-panel">正在加载账号信息…</div>
    <template v-else-if="profile">
      <section class="profile-summary">
        <span class="profile-avatar">{{ initials }}</span>
        <div class="profile-identity"><strong>{{ profile.display_name || '未设置显示名称' }}</strong><small>{{ profile.email }}</small></div>
        <div class="profile-flags"><span class="status-badge"><ShieldCheck :size="12" />{{ roleLabel }}</span><span class="status-badge" data-status="ready"><CheckCircle2 :size="12" />{{ profile.is_active ? '账号正常' : '账号停用' }}</span></div>
      </section>

      <div class="profile-layout">
        <nav class="profile-tabs" aria-label="个人中心栏目">
          <button v-for="tab in tabs" :key="tab.id" type="button" :class="{ active: activeTab === tab.id }" @click="activeTab = tab.id">
            <component :is="tab.icon" :size="17" /><span>{{ tab.label }}</span>
          </button>
        </nav>

        <main class="profile-content">
          <section v-if="activeTab === 'account'" class="account-panel">
            <header><div><h2>账号信息</h2><p>当前信息由服务端账户记录提供。</p></div></header>
            <dl>
              <div><dt><UserRound :size="15" />显示名称</dt><dd>{{ profile.display_name || '未设置' }}</dd></div>
              <div><dt><Mail :size="15" />邮箱</dt><dd>{{ profile.email }}</dd></div>
              <div><dt><ShieldCheck :size="15" />权限角色</dt><dd>{{ roleLabel }}</dd></div>
              <div><dt><CheckCircle2 :size="15" />账号状态</dt><dd>{{ profile.is_active ? '正常使用' : '已停用' }}</dd></div>
            </dl>
            <aside><ShieldCheck :size="16" /><div><strong>账户隔离</strong><p>聊天记录、长期记忆与用量统计只对当前账号可见。</p></div></aside>
          </section>
          <MemoryCenter v-else-if="activeTab === 'memory'" @error="errorMessage = $event" />
          <UsageCenter v-else @error="errorMessage = $event" />
        </main>
      </div>
    </template>
  </section>
</template>

<style scoped>
.profile-summary { min-height: 82px; display: flex; align-items: center; gap: 13px; padding: 15px 17px; border: 1px solid var(--border-default); border-radius: 8px; background: var(--bg-surface); }
.profile-avatar { width: 46px; height: 46px; flex: 0 0 46px; display: grid; place-items: center; border-radius: 8px; color: #fff; background: #3c5d56; font-size: 17px; font-weight: 700; }
.profile-identity { min-width: 0; flex: 1; }
.profile-identity strong, .profile-identity small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.profile-identity strong { color: var(--text-strong); font-size: 14px; }
.profile-identity small { margin-top: 4px; color: var(--text-muted); font-size: 11px; }
.profile-flags { display: flex; gap: 7px; }
.profile-flags .status-badge { gap: 5px; }
.profile-layout { display: grid; grid-template-columns: 190px minmax(0, 1fr); gap: 16px; margin-top: 16px; }
.profile-tabs { align-self: start; display: grid; gap: 3px; padding: 6px; border: 1px solid var(--border-default); border-radius: 8px; background: var(--bg-surface); }
.profile-tabs button { min-height: 40px; display: flex; align-items: center; gap: 9px; padding: 0 10px; border: 0; border-radius: 5px; color: var(--text-muted); background: transparent; cursor: pointer; text-align: left; }
.profile-tabs button:hover { color: var(--text-strong); background: var(--bg-subtle); }
.profile-tabs button.active { color: var(--brand); background: #eaf4f1; font-weight: 600; }
.profile-content { min-width: 0; }
.account-panel { border: 1px solid var(--border-default); border-radius: 8px; background: var(--bg-surface); }
.account-panel > header { padding: 16px; border-bottom: 1px solid var(--border-default); }
.account-panel h2 { margin: 0; color: var(--text-strong); font-size: 15px; }
.account-panel header p { margin: 4px 0 0; color: var(--text-muted); font-size: 11px; }
.account-panel dl { margin: 0; }
.account-panel dl > div { display: grid; grid-template-columns: 180px minmax(0, 1fr); gap: 18px; padding: 14px 16px; border-bottom: 1px solid #edf1f0; }
.account-panel dt { display: flex; align-items: center; gap: 8px; color: var(--text-muted); font-size: 12px; }
.account-panel dd { margin: 0; color: var(--text-strong); font-size: 13px; overflow-wrap: anywhere; }
.account-panel aside { display: flex; align-items: flex-start; gap: 10px; margin: 16px; padding: 12px; border: 1px solid #c7e3d4; border-radius: 6px; color: var(--brand); background: #f2faf5; }
.account-panel aside svg { flex: 0 0 16px; margin-top: 1px; }
.account-panel aside strong { display: block; color: var(--text-strong); font-size: 12px; }
.account-panel aside p { margin: 3px 0 0; color: var(--text-muted); font-size: 11px; line-height: 18px; }
@media (max-width: 820px) { .profile-layout { grid-template-columns: 1fr; } .profile-tabs { display: flex; overflow-x: auto; } .profile-tabs button { flex: 0 0 auto; } }
@media (max-width: 640px) { .profile-summary { align-items: flex-start; flex-wrap: wrap; } .profile-flags { width: 100%; padding-left: 59px; } .account-panel dl > div { grid-template-columns: 1fr; gap: 5px; } }
</style>
