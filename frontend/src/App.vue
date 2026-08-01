<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Activity,
  BarChart3,
  Bot,
  ChevronDown,
  ClipboardCheck,
  Database,
  FileClock,
  FileText,
  Gauge,
  HeartPulse,
  LayoutDashboard,
  Library,
  ListTodo,
  LogOut,
  Menu,
  MessageCircle,
  PanelLeftClose,
  PanelLeftOpen,
  ScrollText,
  ServerCog,
  ShieldCheck,
  UserRound,
  Users,
} from '@lucide/vue'

import { signOut, useAuthSession } from './auth/session.js'

const route = useRoute()
const router = useRouter()
const auth = useAuthSession()
const drawerOpen = ref(false)
const sidebarCollapsed = ref(false)

const isAdmin = computed(() => ['admin', 'super_admin'].includes(auth.user?.role))
const isSuperAdmin = computed(() => auth.user?.role === 'super_admin')
const userLabel = computed(() => auth.user?.display_name || auth.user?.email || '')
const userInitial = computed(() => userLabel.value.trim().slice(0, 1).toUpperCase() || 'U')
const pageTitle = computed(() => route.meta.title || '医疗知识平台')
const fluidWorkspace = computed(() => ['chat', 'agent'].includes(String(route.name || '')))

const navigationGroups = computed(() => {
  const groups = [
    {
      label: '工作空间',
      items: [
        { to: '/dashboard', label: '工作台', icon: LayoutDashboard },
        { to: '/chat', label: '知识问答', icon: MessageCircle },
        { to: '/agent', label: '资料 Agent', icon: Bot },
      ],
    },
    {
      label: '知识空间',
      items: [
        { to: '/knowledge', label: '公共知识库', icon: Library },
        { to: '/my-documents', label: '我的资料', icon: FileText },
      ],
    },
    {
      label: '账户',
      items: [{ to: '/profile', label: '个人中心', icon: UserRound }],
    },
  ]

  if (isAdmin.value) {
    groups.push({
      label: '运营管理',
      items: [
        { to: '/admin', label: '管理概览', icon: Gauge },
        { to: '/admin/reviews', label: '审核中心', icon: ClipboardCheck },
        { to: '/admin/knowledge-assets', label: '知识资产', icon: Database },
        { to: '/admin/jobs', label: '任务中心', icon: ListTodo },
        { to: '/admin/quality', label: '质量分析', icon: ShieldCheck },
        { to: '/admin/telemetry', label: '运行监控', icon: Activity },
        { to: '/admin/usage', label: '用量管理', icon: BarChart3 },
        { to: '/admin/audit', label: '审计记录', icon: ScrollText },
        { to: '/admin/knowledge', label: '系统资料', icon: ServerCog },
      ],
    })
  }

  if (isSuperAdmin.value) {
    groups.push({
      label: '系统管理',
      items: [{ to: '/super-admin/users', label: '用户与角色', icon: Users }],
    })
  }
  return groups
})

const currentSection = computed(() => {
  for (const group of navigationGroups.value) {
    if (group.items.some((item) => route.path === item.to || route.path.startsWith(`${item.to}/`))) {
      return group.label
    }
  }
  return '医疗知识平台'
})

watch(() => route.fullPath, () => {
  drawerOpen.value = false
})

async function logout() {
  signOut()
  await router.push({ name: 'login' })
}
</script>

<template>
  <div
    v-if="auth.user"
    class="app-shell"
    :class="{ 'app-shell--collapsed': sidebarCollapsed }"
  >
    <button
      v-if="drawerOpen"
      class="drawer-backdrop"
      type="button"
      aria-label="关闭导航"
      @click="drawerOpen = false"
    />

    <aside class="app-sidebar" :class="{ open: drawerOpen }">
      <div class="sidebar-brand-row">
        <router-link class="brand" to="/dashboard" aria-label="Medical RAG 工作台">
          <span class="brand-mark"><HeartPulse :size="19" :stroke-width="2.1" /></span>
          <span class="brand-copy">
            <strong>Medical RAG</strong>
            <small>医疗知识平台</small>
          </span>
        </router-link>
        <button
          class="icon-button sidebar-collapse"
          type="button"
          :title="sidebarCollapsed ? '展开侧栏' : '收起侧栏'"
          :aria-label="sidebarCollapsed ? '展开侧栏' : '收起侧栏'"
          @click="sidebarCollapsed = !sidebarCollapsed"
        >
          <PanelLeftOpen v-if="sidebarCollapsed" :size="17" />
          <PanelLeftClose v-else :size="17" />
        </button>
      </div>

      <nav class="side-nav" aria-label="主导航">
        <section v-for="group in navigationGroups" :key="group.label" class="nav-group">
          <span class="nav-section-title">{{ group.label }}</span>
          <router-link
            v-for="item in group.items"
            :key="item.to"
            :to="item.to"
            :title="sidebarCollapsed ? item.label : undefined"
          >
            <component :is="item.icon" :size="17" :stroke-width="1.9" />
            <span>{{ item.label }}</span>
          </router-link>
        </section>
      </nav>

      <div class="sidebar-footer">
        <div class="sidebar-safety">
          <ShieldCheck :size="16" />
          <span>资料检索系统<br />不构成医疗建议</span>
        </div>
        <small class="sidebar-version">Console v1</small>
      </div>
    </aside>

    <div class="app-workspace">
      <header class="app-topbar">
        <div class="topbar-leading">
          <button
            class="icon-button menu-button"
            type="button"
            title="打开导航"
            aria-label="打开导航"
            :aria-expanded="drawerOpen"
            @click="drawerOpen = true"
          >
            <Menu :size="19" />
          </button>
          <nav class="breadcrumbs" aria-label="面包屑">
            <span>{{ currentSection }}</span>
            <i>/</i>
            <strong>{{ pageTitle }}</strong>
          </nav>
        </div>

        <div class="topbar-actions">
          <span class="system-state" title="应用服务可访问">
            <i />服务在线
          </span>
          <details class="account-menu">
            <summary aria-label="打开账号菜单">
              <span class="account-avatar">{{ userInitial }}</span>
              <span class="account-summary">
                <strong>{{ userLabel }}</strong>
                <small>{{ auth.user.role }}</small>
              </span>
              <ChevronDown :size="15" />
            </summary>
            <div class="account-popover">
              <div class="account-popover-head">
                <strong>{{ userLabel }}</strong>
                <small>{{ auth.user.email }}</small>
              </div>
              <router-link to="/profile"><UserRound :size="16" />个人中心</router-link>
              <button type="button" @click="logout"><LogOut :size="16" />退出登录</button>
            </div>
          </details>
        </div>
      </header>

      <main class="app-content" :class="{ 'app-content--fluid': fluidWorkspace }">
        <router-view />
      </main>
    </div>
  </div>

  <div v-else class="public-shell">
    <header class="public-header">
      <router-link class="brand" to="/">
        <span class="brand-mark"><HeartPulse :size="19" :stroke-width="2.1" /></span>
        <span class="brand-copy">
          <strong>Medical RAG</strong>
          <small>医疗知识平台</small>
        </span>
      </router-link>
      <nav aria-label="公共导航">
        <router-link to="/">系统概览</router-link>
        <router-link class="login-link" to="/login">登录系统</router-link>
      </nav>
    </header>
    <main class="public-content"><router-view /></main>
    <footer>
      <span>Medical RAG</span>
      <span>仅供学习与资料检索，不构成医疗建议。</span>
    </footer>
  </div>
</template>
