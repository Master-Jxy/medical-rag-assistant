<script setup>
import { computed, onMounted, ref } from 'vue'
import { ArrowRight, BookOpenText, CheckCircle2, HeartPulse, RefreshCw, Search, ShieldCheck } from '@lucide/vue'

import { getHealth } from '../api/system'
import { useAuthSession } from '../auth/session.js'

const auth = useAuthSession()
const loading = ref(false)
const backendStatus = ref('unknown')
const errorMessage = ref('')

const statusText = computed(() => {
  if (loading.value) return '正在检查'
  if (backendStatus.value === 'ok') return '服务运行正常'
  if (backendStatus.value === 'error') return '服务暂不可用'
  return '等待检查'
})
const entryRoute = computed(() => auth.user ? '/dashboard' : '/login')

async function checkBackend() {
  loading.value = true
  errorMessage.value = ''
  try {
    const data = await getHealth()
    backendStatus.value = data.status === 'ok' ? 'ok' : 'error'
  } catch {
    backendStatus.value = 'error'
    errorMessage.value = '暂时无法连接服务，请稍后重试。'
  } finally {
    loading.value = false
  }
}

onMounted(checkBackend)
</script>

<template>
  <section class="entry-page">
    <div class="entry-main">
      <div class="entry-title">
        <span class="product-icon"><HeartPulse :size="24" /></span>
        <div><small>MEDICAL KNOWLEDGE PLATFORM</small><h1>医疗知识库助手</h1></div>
      </div>
      <p class="entry-copy">面向医疗资料检索、知识问答和多步骤资料处理的统一工作台。回答保留检索来源，所有模型请求由服务端受控执行。</p>
      <div class="entry-actions">
        <router-link class="primary-entry" :to="entryRoute">进入工作台 <ArrowRight :size="16" /></router-link>
        <a class="secondary-entry" href="#capabilities">查看能力</a>
      </div>

      <section id="capabilities" class="capability-list" aria-label="平台能力">
        <article><span><Search :size="18" /></span><div><h2>检索与问答</h2><p>通过公共医学资料生成带引用的回答，支持连续会话。</p></div></article>
        <article><span><BookOpenText :size="18" /></span><div><h2>知识资产</h2><p>资料提交、审核、发布和向量化状态全程可追踪。</p></div></article>
        <article><span><ShieldCheck :size="18" /></span><div><h2>权限与审计</h2><p>区分普通用户、管理员与超级管理员操作边界。</p></div></article>
      </section>
    </div>

    <aside class="system-panel" aria-label="系统状态">
      <header><div><span>SERVICE STATUS</span><h2>服务状态</h2></div><button class="icon-button" type="button" title="重新检查" :disabled="loading" @click="checkBackend"><RefreshCw :size="16" :class="{ spinning: loading }" /></button></header>
      <div class="status-summary" :data-status="backendStatus">
        <span class="status-mark"><CheckCircle2 :size="19" /></span>
        <div><strong>{{ statusText }}</strong><small>{{ errorMessage || 'FastAPI 健康检查已连接' }}</small></div>
      </div>
      <dl>
        <div><dt>知识问答</dt><dd>可用</dd></div>
        <div><dt>资料 Agent</dt><dd>可用</dd></div>
        <div><dt>知识库</dt><dd>公共资料</dd></div>
        <div><dt>访问方式</dt><dd>账号登录</dd></div>
      </dl>
      <p class="safety-note"><ShieldCheck :size="15" />仅供学习和信息检索，不构成医疗建议。</p>
    </aside>
  </section>
</template>

<style scoped>
.entry-page { min-height: calc(100vh - 166px); display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(330px, .65fr); align-items: center; gap: clamp(36px, 7vw, 88px); padding: 56px 0; }
.entry-main { max-width: 700px; }
.entry-title { display: flex; align-items: center; gap: 14px; }
.product-icon { width: 48px; height: 48px; flex: 0 0 48px; display: grid; place-items: center; border-radius: 8px; color: #fff; background: var(--brand); }
.entry-title small { color: var(--brand); font-size: 10px; font-weight: 700; }
.entry-title h1 { margin: 2px 0 0; color: var(--text-strong); font-size: 30px; line-height: 38px; letter-spacing: 0; }
.entry-copy { max-width: 650px; margin: 22px 0 0; color: var(--text-muted); font-size: 15px; line-height: 25px; }
.entry-actions { display: flex; gap: 9px; margin-top: 26px; }
.primary-entry, .secondary-entry { min-height: 38px; display: inline-flex; align-items: center; justify-content: center; gap: 7px; padding: 0 15px; border-radius: 6px; font-size: 13px; font-weight: 600; }
.primary-entry { color: #fff; background: var(--action); }
.primary-entry:hover { background: var(--action-hover); }
.secondary-entry { border: 1px solid var(--border-default); background: var(--bg-surface); }
.capability-list { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); margin-top: 42px; border-top: 1px solid var(--border-default); }
.capability-list article { display: flex; gap: 10px; padding: 19px 16px 0 0; }
.capability-list article > span { width: 32px; height: 32px; flex: 0 0 32px; display: grid; place-items: center; border-radius: 6px; color: var(--brand); background: #eaf4f1; }
.capability-list h2 { margin: 0; color: var(--text-strong); font-size: 13px; }
.capability-list p { margin: 5px 0 0; color: var(--text-muted); font-size: 11px; line-height: 18px; }
.system-panel { padding: 20px; border: 1px solid var(--border-default); border-radius: 8px; background: var(--bg-surface); box-shadow: 0 14px 38px rgba(23, 32, 30, .08); }
.system-panel header { display: flex; align-items: center; justify-content: space-between; }
.system-panel header span { color: var(--brand); font-size: 10px; font-weight: 700; }
.system-panel h2 { margin: 3px 0 0; color: var(--text-strong); font-size: 16px; }
.status-summary { display: flex; align-items: center; gap: 11px; margin: 18px 0; padding: 13px; border: 1px solid #c7e3d4; border-radius: 7px; background: #f2faf5; }
.status-summary[data-status="error"] { border-color: #efc3bf; background: #fff8f7; }
.status-mark { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 6px; color: var(--success); background: #e3f4ea; }
.status-summary[data-status="error"] .status-mark { color: var(--danger); background: #fde8e6; }
.status-summary strong, .status-summary small { display: block; }
.status-summary strong { color: var(--text-strong); font-size: 13px; }
.status-summary small { margin-top: 2px; color: var(--text-muted); font-size: 11px; }
.system-panel dl { margin: 0; border-top: 1px solid var(--border-default); }
.system-panel dl div { display: flex; justify-content: space-between; gap: 18px; padding: 11px 2px; border-bottom: 1px solid #edf1f0; font-size: 12px; }
.system-panel dt { color: var(--text-muted); }
.system-panel dd { margin: 0; color: var(--text-strong); font-weight: 600; }
.safety-note { display: flex; align-items: flex-start; gap: 7px; margin: 16px 0 0; color: var(--text-muted); font-size: 11px; line-height: 18px; }
.safety-note svg { flex: 0 0 15px; margin-top: 1px; }
.spinning { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) { .entry-page { grid-template-columns: 1fr; align-items: start; padding: 38px 0; } .system-panel { max-width: 620px; } }
@media (max-width: 640px) { .entry-title h1 { font-size: 24px; line-height: 32px; } .capability-list { grid-template-columns: 1fr; } .capability-list article { padding-top: 16px; } .entry-actions { align-items: stretch; flex-direction: column; } }
</style>
