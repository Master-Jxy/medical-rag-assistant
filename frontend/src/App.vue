<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import { signOut, useAuthSession } from './auth/session.js'

const router = useRouter()
const auth = useAuthSession()
const userLabel = computed(() => auth.user?.display_name || auth.user?.email || '')

async function logout() {
  signOut()
  await router.push({ name: 'login' })
}
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <router-link class="brand" to="/">
        <span class="brand-mark">M</span>
        <span><strong>Medical RAG</strong><small>医疗知识库助手</small></span>
      </router-link>
      <nav aria-label="主导航">
        <router-link to="/">系统概览</router-link>
        <router-link to="/chat">知识问答</router-link>
        <router-link to="/knowledge">知识库</router-link>
        <router-link v-if="auth.user?.role === 'admin'" to="/admin/knowledge">系统管理</router-link>
        <div v-if="auth.user" class="account-menu">
          <span :title="auth.user.email">{{ userLabel }}</span>
          <button @click="logout">退出</button>
        </div>
        <router-link v-else class="login-link" to="/login">登录</router-link>
      </nav>
    </header>
    <main><router-view /></main>
    <footer>仅供学习和信息检索，不构成医疗建议。</footer>
  </div>
</template>
