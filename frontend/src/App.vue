<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { signOut, useAuthSession } from './auth/session.js'

const route = useRoute()
const router = useRouter()
const auth = useAuthSession()
const drawerOpen = ref(false)

const userLabel = computed(() => auth.user?.display_name || auth.user?.email || '')
const isAdmin = computed(() => ['admin', 'super_admin'].includes(auth.user?.role))
const isSuperAdmin = computed(() => auth.user?.role === 'super_admin')
const pageTitle = computed(() => route.meta.title || '医疗知识库助手')
const publicItems = [
  { to: '/dashboard', label: '工作台' },
  { to: '/chat', label: '知识问答' },
  { to: '/agent', label: 'Agent' },
  { to: '/knowledge', label: '公共知识库' },
  { to: '/my-documents', label: '我的资料' },
  { to: '/profile', label: '个人中心' },
]
const adminItems = [
  { to: '/admin', label: '管理概览' },
  { to: '/admin/reviews', label: '审核中心' },
  { to: '/admin/knowledge-assets', label: '知识资产' },
  { to: '/admin/jobs', label: '任务中心' },
  { to: '/admin/audit', label: '审计记录' },
  { to: '/admin/knowledge', label: '系统资料' },
  { to: '/admin/telemetry', label: '运行统计' },
  { to: '/admin/quality', label: '回答质量' },
  { to: '/admin/usage', label: '用量管理' },
]

watch(() => route.fullPath, () => {
  drawerOpen.value = false
})

async function logout() {
  signOut()
  await router.push({ name: 'login' })
}
</script>

<template>
  <div v-if="auth.user" class="app-shell">
    <button
      v-if="drawerOpen"
      class="drawer-backdrop"
      aria-label="关闭导航"
      @click="drawerOpen = false"
    />
    <aside class="app-sidebar" :class="{ open: drawerOpen }">
      <router-link class="brand" to="/dashboard">
        <span class="brand-mark">M</span>
        <span><strong>Medical RAG</strong><small>医疗知识库助手</small></span>
      </router-link>
      <nav class="side-nav" aria-label="主导航">
        <span class="nav-section-title">个人空间</span>
        <router-link v-for="item in publicItems" :key="item.to" :to="item.to">
          {{ item.label }}
        </router-link>
        <template v-if="isAdmin">
          <span class="nav-section-title">管理中台</span>
          <router-link v-for="item in adminItems" :key="item.to" :to="item.to">
            {{ item.label }}
          </router-link>
        </template>
        <template v-if="isSuperAdmin">
          <span class="nav-section-title">超级管理</span>
          <router-link to="/super-admin/users">用户与角色</router-link>
        </template>
      </nav>
      <p class="sidebar-note">仅供学习和资料检索，不构成医疗建议。</p>
    </aside>

    <div class="app-workspace">
      <header class="app-topbar">
        <button
          class="menu-button"
          aria-label="打开导航"
          :aria-expanded="drawerOpen"
          @click="drawerOpen = true"
        >
          ☰
        </button>
        <div class="page-identity">
          <small>医疗知识库 /</small>
          <strong>{{ pageTitle }}</strong>
        </div>
        <div class="topbar-actions">
          <span class="system-state"><i />已登录</span>
          <span class="account-name" :title="auth.user.email">{{ userLabel }}</span>
          <button class="quiet-button" @click="logout">退出</button>
        </div>
      </header>
      <main class="app-content"><router-view /></main>
    </div>
  </div>

  <div v-else class="public-shell">
    <header class="public-header">
      <router-link class="brand" to="/">
        <span class="brand-mark">M</span>
        <span><strong>Medical RAG</strong><small>医疗知识库助手</small></span>
      </router-link>
      <nav aria-label="公共导航">
        <router-link to="/">系统概览</router-link>
        <router-link class="login-link" to="/login">登录</router-link>
      </nav>
    </header>
    <main class="public-content"><router-view /></main>
    <footer>仅供学习和信息检索，不构成医疗建议。</footer>
  </div>
</template>
