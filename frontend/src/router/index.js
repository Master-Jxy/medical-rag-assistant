import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import ChatView from '../views/ChatView.vue'
import KnowledgeView from '../views/KnowledgeView.vue'
import LoginView from '../views/LoginView.vue'
import AdminKnowledgeView from '../views/AdminKnowledgeView.vue'
import { initializeAuth, useAuthSession } from '../auth/session.js'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/login', name: 'login', component: LoginView, meta: { guestOnly: true } },
    { path: '/chat', name: 'chat', component: ChatView, meta: { requiresAuth: true } },
    { path: '/knowledge', name: 'knowledge', component: KnowledgeView, meta: { requiresAuth: true } },
    {
      path: '/admin/knowledge',
      name: 'admin-knowledge',
      component: AdminKnowledgeView,
      meta: { requiresAuth: true, requiresAdmin: true },
    },
  ],
})

function safeRedirect(value, fallback = '/chat') {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//')
    ? value
    : fallback
}

router.beforeEach(async (to) => {
  await initializeAuth()
  const auth = useAuthSession()

  if (to.meta.requiresAuth && !auth.user) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.requiresAdmin && auth.user?.role !== 'admin') return { name: 'knowledge' }
  if (to.meta.guestOnly && auth.user) return safeRedirect(to.query.redirect)
  return true
})

export default router
