import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import ChatView from '../views/ChatView.vue'
import KnowledgeView from '../views/KnowledgeView.vue'
import LoginView from '../views/LoginView.vue'
import DashboardView from '../views/DashboardView.vue'
import ProfileView from '../views/ProfileView.vue'
import MyDocumentsView from '../views/MyDocumentsView.vue'
import AdminOverviewView from '../views/AdminOverviewView.vue'
import AdminReviewsView from '../views/AdminReviewsView.vue'
import AdminAssetsView from '../views/AdminAssetsView.vue'
import AdminJobsView from '../views/AdminJobsView.vue'
import AdminAuditView from '../views/AdminAuditView.vue'
import AdminKnowledgeView from '../views/AdminKnowledgeView.vue'
import AdminTelemetryView from '../views/AdminTelemetryView.vue'
import SuperAdminUsersView from '../views/SuperAdminUsersView.vue'
import AgentView from '../views/AgentView.vue'
import AdminQualityView from '../views/AdminQualityView.vue'
import { initializeAuth, useAuthSession } from '../auth/session.js'

const authenticated = { requiresAuth: true }
const adminOnly = { requiresAuth: true, roles: ['admin', 'super_admin'] }
const superAdminOnly = { requiresAuth: true, roles: ['super_admin'] }

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView, meta: { title: '系统概览' } },
    { path: '/login', name: 'login', component: LoginView, meta: { guestOnly: true, title: '登录' } },
    { path: '/dashboard', name: 'dashboard', component: DashboardView, meta: { ...authenticated, title: '工作台' } },
    { path: '/chat', name: 'chat', component: ChatView, meta: { ...authenticated, title: '知识问答' } },
    { path: '/agent', name: 'agent', component: AgentView, meta: { ...authenticated, title: 'Agent' } },
    { path: '/knowledge', name: 'knowledge', component: KnowledgeView, meta: { ...authenticated, title: '公共知识库' } },
    { path: '/my-documents', name: 'my-documents', component: MyDocumentsView, meta: { ...authenticated, title: '我的资料' } },
    { path: '/profile', name: 'profile', component: ProfileView, meta: { ...authenticated, title: '个人中心' } },
    { path: '/admin', name: 'admin-overview', component: AdminOverviewView, meta: { ...adminOnly, title: '管理概览' } },
    { path: '/admin/reviews', name: 'admin-reviews', component: AdminReviewsView, meta: { ...adminOnly, title: '审核中心' } },
    { path: '/admin/knowledge-assets', name: 'admin-assets', component: AdminAssetsView, meta: { ...adminOnly, title: '知识资产' } },
    { path: '/admin/jobs', name: 'admin-jobs', component: AdminJobsView, meta: { ...adminOnly, title: '任务中心' } },
    { path: '/admin/audit', name: 'admin-audit', component: AdminAuditView, meta: { ...adminOnly, title: '审计记录' } },
    { path: '/admin/knowledge', name: 'admin-knowledge', component: AdminKnowledgeView, meta: { ...adminOnly, title: '系统资料' } },
    { path: '/admin/telemetry', name: 'admin-telemetry', component: AdminTelemetryView, meta: { ...adminOnly, title: '运行统计' } },
    { path: '/admin/quality', name: 'admin-quality', component: AdminQualityView, meta: { ...adminOnly, title: '回答质量' } },
    { path: '/super-admin/users', name: 'super-admin-users', component: SuperAdminUsersView, meta: { ...superAdminOnly, title: '用户与角色' } },
  ],
})

function safeRedirect(value, fallback = '/dashboard') {
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
  if (to.meta.roles && !to.meta.roles.includes(auth.user?.role)) {
    return { name: 'knowledge' }
  }
  if (to.meta.guestOnly && auth.user) return safeRedirect(to.query.redirect)
  return true
})

export default router
