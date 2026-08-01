<script setup>
import { computed, onMounted, ref } from 'vue'
import { RefreshCw, ShieldCheck, UserCheck, UserRoundCog, UsersRound } from '@lucide/vue'

import ConfirmDialog from '../components/ConfirmDialog.vue'
import { getUsers, updateUserRole, updateUserStatus } from '../api/adminPlatform'
import { getApiErrorMessage } from '../api/http'

const items = ref([])
const loading = ref(true)
const errorMessage = ref('')
const actingId = ref('')
const actionTarget = ref(null)
const actionType = ref('')
const activeCount = computed(() => items.value.filter((item) => item.is_active).length)
const adminCount = computed(() => items.value.filter((item) => ['admin', 'super_admin'].includes(item.role)).length)
const roleLabels = { user: '普通用户', admin: '管理员', super_admin: '超级管理员' }

async function load() {
  loading.value = true
  try {
    items.value = (await getUsers()).items
    errorMessage.value = ''
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    loading.value = false
  }
}

function requestAction(item, type) {
  actionTarget.value = item
  actionType.value = type
}

async function confirmAction() {
  if (!actionTarget.value || actingId.value) return
  const item = actionTarget.value
  actingId.value = item.id
  try {
    if (actionType.value === 'role') {
      await updateUserRole(item.id, item.role === 'admin' ? 'user' : 'admin')
    } else {
      await updateUserStatus(item.id, !item.is_active)
    }
    actionTarget.value = null
    await load()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    actingId.value = ''
  }
}

onMounted(load)
</script>

<template>
  <section class="platform-page">
    <header class="page-toolbar"><div><span>SUPER ADMIN</span><h1>用户与角色</h1><p>管理账号状态并控制管理员权限。</p></div><button class="secondary-action" type="button" :disabled="loading" @click="load"><RefreshCw :size="15" />刷新</button></header>
    <div class="metric-grid user-metrics"><article><small>全部用户</small><strong>{{ items.length }}</strong><UsersRound :size="18" /></article><article><small>正常账号</small><strong>{{ activeCount }}</strong><UserCheck :size="18" /></article><article><small>管理角色</small><strong>{{ adminCount }}</strong><ShieldCheck :size="18" /></article></div>
    <div v-if="errorMessage" class="state-panel error">{{ errorMessage }}</div>
    <div v-if="loading" class="state-panel">正在加载用户…</div>
    <section v-else class="table-panel responsive-table users-table"><div class="user-head"><span>账号</span><span>角色</span><span>状态</span><span>注册时间</span><span>操作</span></div><div v-for="item in items" :key="item.id" class="user-row"><div class="user-cell"><span>{{ (item.display_name || item.email).slice(0, 1).toUpperCase() }}</span><div><strong :title="item.email">{{ item.display_name || '未设置名称' }}</strong><small>{{ item.email }}</small></div></div><span class="status-badge">{{ roleLabels[item.role] || item.role }}</span><span class="status-badge" :data-status="item.is_active ? 'ready' : 'failed'">{{ item.is_active ? '正常' : '停用' }}</span><span>{{ new Date(item.created_at).toLocaleDateString() }}</span><div v-if="item.role !== 'super_admin'" class="user-actions"><button class="text-action" type="button" @click="requestAction(item, 'role')">{{ item.role === 'admin' ? '撤销管理员' : '设为管理员' }}</button><button class="text-action" :class="item.is_active ? 'danger' : 'success'" type="button" @click="requestAction(item, 'status')">{{ item.is_active ? '停用' : '启用' }}</button></div><span v-else class="protected-user"><ShieldCheck :size="14" />受保护</span></div></section>
    <ConfirmDialog :open="Boolean(actionTarget)" :tone="actionType === 'status' && actionTarget?.is_active ? 'danger' : 'warning'" :title="actionType === 'role' ? (actionTarget?.role === 'admin' ? '撤销管理员权限？' : '授予管理员权限？') : (actionTarget?.is_active ? '停用这个账号？' : '启用这个账号？')" :description="actionTarget ? `${actionTarget.email} 的权限或状态将立即更新并写入审计记录。` : ''" confirm-text="确认变更" :loading="Boolean(actingId)" @cancel="actionTarget = null" @confirm="confirmAction" />
  </section>
</template>

<style scoped>
.secondary-action { min-height: 34px; display: inline-flex; align-items: center; gap: 7px; padding: 0 12px; border: 1px solid var(--border-default); border-radius: 6px; color: var(--text-default); background: #fff; cursor: pointer; }
.user-metrics article { position: relative; }
.user-metrics article > svg { position: absolute; top: 16px; right: 16px; color: var(--text-muted); }
.user-head, .user-row { min-width: 860px; display: grid; grid-template-columns: minmax(230px, 1.35fr) .75fr .6fr .8fr 1.1fr; align-items: center; gap: 14px; padding: 11px 15px; }
.user-head { color: var(--text-muted); background: var(--bg-subtle); font-size: 11px; font-weight: 700; }
.user-row { min-height: 58px; border-top: 1px solid #edf1f0; color: var(--text-muted); font-size: 11px; }
.user-cell { min-width: 0; display: flex; align-items: center; gap: 9px; }
.user-cell > span { width: 32px; height: 32px; flex: 0 0 32px; display: grid; place-items: center; border-radius: 6px; color: #fff; background: #3c5d56; font-weight: 700; }
.user-cell > div { min-width: 0; }
.user-cell strong, .user-cell small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.user-cell strong { color: var(--text-strong); font-size: 11px; }
.user-cell small { margin-top: 2px; color: var(--text-muted); font-size: 10px; }
.user-actions { display: flex; gap: 12px; }
.text-action { padding: 3px 0; border: 0; color: var(--action); background: transparent; cursor: pointer; font-size: 11px; }
.text-action.danger { color: var(--danger); }
.text-action.success { color: var(--success); }
.protected-user { display: flex; align-items: center; gap: 5px; color: var(--text-muted); }
</style>
