<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  Activity,
  ArrowRight,
  BookOpenCheck,
  Bot,
  BrainCircuit,
  CheckCircle2,
  FileSearch,
  GitBranch,
  HeartPulse,
  Layers3,
  LockKeyhole,
  MessageSquareText,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Workflow,
} from '@lucide/vue'

import { getHealth } from '../api/system'
import { useAuthSession } from '../auth/session.js'

const auth = useAuthSession()
const pageRoot = ref(null)
const statsSection = ref(null)
const loading = ref(false)
const backendStatus = ref('unknown')
const errorMessage = ref('')

const stats = [
  { value: 3, suffix: '级', label: '清晰权限角色' },
  { value: 2, suffix: '种', label: '独立对话工作区' },
  { value: 4, suffix: '层', label: '资料治理流程' },
  { value: 1, suffix: '套', label: '统一用量体系' },
]
const counterValues = ref(stats.map(() => 0))
const technologies = [
  'Vue 3', 'FastAPI', 'LangChain', 'DashScope', 'Chroma', 'MySQL', 'Redis', 'SSE',
]

let revealObserver = null
let statsObserver = null
let animationFrame = null

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

function animateStats() {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (reduceMotion) {
    counterValues.value = stats.map((item) => item.value)
    return
  }
  const startedAt = performance.now()
  const duration = 1500
  const tick = (now) => {
    const progress = Math.min((now - startedAt) / duration, 1)
    const eased = 1 - Math.pow(1 - progress, 4)
    counterValues.value = stats.map((item) => Math.round(item.value * eased))
    if (progress < 1) animationFrame = window.requestAnimationFrame(tick)
  }
  animationFrame = window.requestAnimationFrame(tick)
}

function setupMotion() {
  const revealItems = pageRoot.value?.querySelectorAll('[data-reveal]') || []
  if (!('IntersectionObserver' in window)) {
    revealItems.forEach((item) => item.classList.add('is-visible'))
    animateStats()
    return
  }
  revealObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return
      entry.target.classList.add('is-visible')
      revealObserver?.unobserve(entry.target)
    })
  }, { threshold: 0.14 })
  revealItems.forEach((item) => revealObserver.observe(item))

  statsObserver = new IntersectionObserver((entries) => {
    if (!entries.some((entry) => entry.isIntersecting)) return
    animateStats()
    statsObserver?.disconnect()
  }, { threshold: 0.35 })
  if (statsSection.value) statsObserver.observe(statsSection.value)
}

onMounted(() => {
  checkBackend()
  setupMotion()
})

onBeforeUnmount(() => {
  revealObserver?.disconnect()
  statsObserver?.disconnect()
  if (animationFrame) window.cancelAnimationFrame(animationFrame)
})
</script>

<template>
  <div ref="pageRoot" class="overview-page">
    <section class="overview-hero" data-reveal>
      <div class="hero-grid" aria-hidden="true"></div>
      <div class="hero-copy">
        <div class="hero-brand"><HeartPulse :size="17" /> Medical RAG 医疗知识平台</div>
        <h1>把医学资料变成<br /><strong>可检索、可追溯的知识工作台</strong></h1>
        <p>从资料提交与审核，到 RAG 问答、Agent 执行、长期记忆和用量治理，一套系统完成知识应用的完整闭环。</p>
        <div class="hero-points">
          <span><CheckCircle2 :size="15" />回答保留来源</span>
          <span><CheckCircle2 :size="15" />SSE 流式响应</span>
          <span><CheckCircle2 :size="15" />账号数据隔离</span>
        </div>
        <div class="entry-actions">
          <router-link class="primary-entry" :to="entryRoute">进入工作台 <ArrowRight :size="16" /></router-link>
          <a class="secondary-entry" href="#capabilities">查看平台能力</a>
        </div>
      </div>

      <aside class="hero-console" aria-label="平台运行概览">
        <header>
          <div><span class="live-dot"></span><strong>平台运行概览</strong></div>
          <button class="icon-button" type="button" title="重新检查" :disabled="loading" @click="checkBackend"><RefreshCw :size="16" :class="{ spinning: loading }" /></button>
        </header>
        <div class="hero-status" :data-status="backendStatus">
          <Activity :size="22" />
          <div><strong>{{ statusText }}</strong><small>{{ errorMessage || 'FastAPI 健康检查已连接' }}</small></div>
        </div>
        <div class="console-flow">
          <div><span><FileSearch :size="17" /></span><p><strong>资料进入知识库</strong><small>解析、切分、审核和向量化状态可追踪</small></p></div>
          <div><span><MessageSquareText :size="17" /></span><p><strong>检索形成上下文</strong><small>混合检索与来源引用约束模型回答</small></p></div>
          <div><span><ShieldCheck :size="17" /></span><p><strong>结果受控交付</strong><small>权限、额度、日志和反馈形成治理闭环</small></p></div>
        </div>
      </aside>
    </section>

    <section class="technology-rail" aria-label="项目技术生态">
      <p>项目技术生态</p>
      <div class="rail-window">
        <div class="rail-track">
          <span v-for="(technology, index) in [...technologies, ...technologies]" :key="`${technology}-${index}`"><i></i>{{ technology }}</span>
        </div>
      </div>
    </section>

    <section id="capabilities" class="overview-section capability-section" data-reveal>
      <header class="section-heading">
        <div><h2>从资料到回答，不只是一页聊天</h2><p>核心业务被拆成独立模块，通过稳定接口协作，后续功能可以持续扩展。</p></div>
        <span><Layers3 :size="18" />模块化单体架构</span>
      </header>
      <div class="capability-grid">
        <article class="capability-primary">
          <div class="capability-icon"><MessageSquareText :size="23" /></div>
          <div><h3>RAG 知识问答</h3><p>从公共医学资料中检索相关片段，结合多轮上下文生成回答，并展示文档、页码与原文来源。</p></div>
          <ul><li>流式输出与停止生成</li><li>历史会话持久化</li><li>引用来源与质量反馈</li></ul>
        </article>
        <article><Bot :size="22" /><h3>受控 Agent</h3><p>按任务动态规划工具调用，公开展示执行事件，完成后折叠过程并保留最终产物。</p></article>
        <article><BookOpenCheck :size="22" /><h3>知识治理</h3><p>用户提交资料，管理员审核发布，系统记录解析、向量化和复核状态。</p></article>
        <article><BrainCircuit :size="22" /><h3>长期记忆</h3><p>用户可查看、审批、编辑或关闭记忆，让 RAG 与 Agent 获得可控的个性化上下文。</p></article>
        <article><LockKeyhole :size="22" /><h3>认证与额度</h3><p>邮箱认证、三层角色、用户用量与管理员额度治理共同保护模型服务。</p></article>
        <article><Activity :size="22" /><h3>质量与运行</h3><p>回答反馈、请求标识、模型用量、任务状态和审计记录支持持续排查与改进。</p></article>
      </div>
    </section>

    <section class="overview-section workflow-section" data-reveal>
      <header class="section-heading"><div><h2>一条可以解释的工作链路</h2><p>每一步都有明确输入、状态和责任边界，避免把所有功能堆进一个聊天函数。</p></div><span><Workflow :size="18" />真实业务闭环</span></header>
      <div class="workflow-line">
        <article><b>1</b><div><h3>资料提交</h3><p>文件或网页快照进入待审核区，保留上传者与文件状态。</p></div></article>
        <article><b>2</b><div><h3>审核发布</h3><p>管理员确认内容后写入公共知识库并建立向量索引。</p></div></article>
        <article><b>3</b><div><h3>检索执行</h3><p>RAG 或 Agent 调用共享检索能力，获得受控上下文。</p></div></article>
        <article><b>4</b><div><h3>反馈治理</h3><p>来源、用量、反馈和审计信息回到管理端持续分析。</p></div></article>
      </div>
    </section>

    <section class="overview-section workspace-section" data-reveal>
      <div class="workspace-copy">
        <h2>用户工作台与管理中台各司其职</h2>
        <p>普通用户专注于提问、资料和个人数据；管理员在独立界面处理审核、知识资产、质量和全站用量。</p>
        <div class="workspace-tabs"><span class="active">普通用户</span><span>管理员</span><span>超级管理员</span></div>
      </div>
      <div class="workspace-preview">
        <header><span></span><span></span><span></span><strong>Medical RAG Workspace</strong></header>
        <div class="preview-body">
          <nav><i></i><i></i><i></i><i></i><i></i></nav>
          <main>
            <div class="preview-toolbar"></div>
            <section><div class="preview-message short"></div><div class="preview-message user"></div><div class="preview-message long"></div></section>
            <footer><div></div><button aria-hidden="true"></button></footer>
          </main>
        </div>
      </div>
    </section>

    <section ref="statsSection" class="overview-section stats-section" data-reveal>
      <header class="section-heading"><div><h2>复杂度来自真实边界，不来自功能堆叠</h2><p>角色、工作区、治理流程和用量体系都保持清晰的模块归属。</p></div></header>
      <div class="stats-grid">
        <article v-for="(item, index) in stats" :key="item.label"><strong>{{ counterValues[index] }}<small>{{ item.suffix }}</small></strong><span>{{ item.label }}</span></article>
      </div>
    </section>

    <section class="overview-section architecture-section" data-reveal>
      <div class="architecture-copy"><GitBranch :size="23" /><h2>适合持续开发，也适合稳定部署</h2><p>前端、接口、业务服务和数据基础设施按层组织。本地开发完成后，通过 GitHub 和 Docker Compose 发布到服务器，Web 可独立更新。</p></div>
      <div class="architecture-stack">
        <div><span>交互层</span><strong>Vue 3 · Vite · SSE</strong></div>
        <div><span>接口层</span><strong>FastAPI · Pydantic</strong></div>
        <div><span>业务层</span><strong>RAG · Agent · Auth · Usage</strong></div>
        <div><span>数据层</span><strong>MySQL · Chroma · Redis</strong></div>
      </div>
    </section>

    <section class="overview-cta" data-reveal>
      <div><Sparkles :size="22" /><h2>开始使用医疗知识工作台</h2><p>登录后即可进入知识问答、Agent、公共知识库和个人用量中心。</p></div>
      <router-link :to="entryRoute">{{ auth.user ? '返回工作台' : '登录系统' }} <ArrowRight :size="16" /></router-link>
    </section>

    <p class="overview-safety"><ShieldCheck :size="15" />系统仅用于学习和医学资料检索，不提供临床诊断、处方或治疗建议。</p>
  </div>
</template>

<style scoped>
.overview-page { --home-blue: #2563eb; --home-cyan: #10b7c4; display: grid; gap: 76px; padding: 42px 0 28px; }
[data-reveal] { opacity: 0; transform: translateY(22px); transition: opacity .65s cubic-bezier(.16,1,.3,1), transform .65s cubic-bezier(.16,1,.3,1); }
[data-reveal].is-visible { opacity: 1; transform: translateY(0); }
.overview-hero { position: relative; min-height: 650px; display: grid; grid-template-columns: minmax(0, 1.04fr) minmax(390px, .72fr); align-items: center; gap: clamp(34px, 6vw, 88px); overflow: hidden; padding: clamp(48px, 7vw, 88px); border: 1px solid rgba(109,143,216,.16); border-radius: 26px; background: linear-gradient(135deg, rgba(242,248,255,.88), rgba(236,244,255,.7) 58%, rgba(226,235,255,.86)); box-shadow: 0 28px 80px rgba(45,82,155,.1); }
.hero-grid { position: absolute; inset: 0; opacity: .62; background-image: linear-gradient(rgba(78,121,205,.08) 1px, transparent 1px), linear-gradient(90deg, rgba(78,121,205,.08) 1px, transparent 1px); background-size: 46px 46px; mask-image: linear-gradient(to right, #000 0%, rgba(0,0,0,.88) 58%, transparent 100%); }
.hero-copy, .hero-console { position: relative; z-index: 1; }
.hero-brand { width: fit-content; display: flex; align-items: center; gap: 8px; padding: 8px 12px; border: 1px solid rgba(37,99,235,.2); border-radius: 999px; color: #1d55bd; background: rgba(255,255,255,.64); font-size: 12px; font-weight: 650; }
.hero-copy h1 { max-width: 720px; margin: 24px 0 18px; color: #182130; font-size: clamp(42px, 4.4vw, 66px); line-height: 1.08; font-weight: 760; letter-spacing: 0; }
.hero-copy h1 strong { color: var(--home-blue); font-weight: inherit; background: linear-gradient(90deg, #2563eb 0%, #08aeca 42%, #7158f5 72%, #2563eb 100%); background-size: 200% auto; background-clip: text; -webkit-background-clip: text; -webkit-text-fill-color: transparent; animation: title-gradient-flow 4.8s linear infinite; }
@keyframes title-gradient-flow { from { background-position: 0% center; } to { background-position: 200% center; } }
.hero-copy > p { max-width: 650px; margin: 0; color: #536078; font-size: 16px; line-height: 1.9; }
.hero-points { display: flex; flex-wrap: wrap; gap: 9px 18px; margin-top: 24px; color: #40506b; font-size: 13px; }
.hero-points span { display: inline-flex; align-items: center; gap: 6px; }
.hero-points svg { color: var(--home-blue); }
.entry-actions { display: flex; gap: 12px; margin-top: 30px; }
.primary-entry, .secondary-entry { min-height: 48px; display: inline-flex; align-items: center; justify-content: center; gap: 8px; padding: 0 20px; border-radius: 12px; font-size: 14px; font-weight: 650; transition: transform .18s ease, box-shadow .18s ease, background .18s ease; }
.primary-entry { color: #fff; background: var(--home-blue); box-shadow: 0 14px 30px rgba(37,99,235,.24); }
.secondary-entry { border: 1px solid rgba(37,99,235,.18); color: #26364f; background: rgba(255,255,255,.72); }
.primary-entry:hover, .secondary-entry:hover { transform: translateY(-2px); }
.hero-console { padding: 20px; border: 1px solid rgba(255,255,255,.86); border-radius: 20px; background: rgba(255,255,255,.75); box-shadow: 0 26px 70px rgba(45,82,155,.13), inset 0 1px #fff; backdrop-filter: blur(18px); }
.hero-console > header { display: flex; align-items: center; justify-content: space-between; min-height: 42px; }
.hero-console > header > div { display: flex; align-items: center; gap: 8px; color: #26364f; font-size: 13px; }
.live-dot { width: 8px; height: 8px; border-radius: 50%; background: #31b77a; box-shadow: 0 0 0 5px rgba(49,183,122,.12); }
.hero-status { display: flex; align-items: center; gap: 12px; margin: 12px 0; padding: 17px; border: 1px solid rgba(49,183,122,.18); border-radius: 14px; color: #18825a; background: rgba(237,250,244,.84); }
.hero-status[data-status="error"] { color: #b54b56; border-color: rgba(215,91,97,.2); background: rgba(255,241,242,.84); }
.hero-status strong, .hero-status small { display: block; }
.hero-status strong { color: #213047; font-size: 14px; }
.hero-status small { margin-top: 3px; color: #6d788c; font-size: 11px; }
.console-flow { display: grid; gap: 8px; }
.console-flow > div { display: flex; align-items: center; gap: 12px; padding: 13px; border: 1px solid rgba(71,105,172,.1); border-radius: 12px; background: rgba(247,250,255,.8); }
.console-flow > div > span { width: 36px; height: 36px; flex: 0 0 36px; display: grid; place-items: center; border-radius: 10px; color: var(--home-blue); background: #eaf1ff; }
.console-flow p, .console-flow strong, .console-flow small { display: block; margin: 0; }
.console-flow strong { color: #26364f; font-size: 12px; }
.console-flow small { margin-top: 4px; color: #748096; font-size: 10px; line-height: 1.5; }
.spinning { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.technology-rail { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 30px; padding: 2px 0; overflow: hidden; }
.technology-rail > p { margin: 0; color: #718099; font-size: 12px; white-space: nowrap; }
.rail-window { min-width: 0; overflow: hidden; mask-image: linear-gradient(to right, transparent, #000 7%, #000 93%, transparent); }
.rail-track { width: max-content; display: flex; align-items: center; gap: 44px; animation: rail-forward 28s linear infinite; }
.rail-track:hover { animation-play-state: paused; }
.rail-track span { display: inline-flex; align-items: center; gap: 9px; color: #526179; font-size: 14px; font-weight: 650; white-space: nowrap; opacity: .72; transition: color .2s ease, opacity .2s ease, transform .2s cubic-bezier(.16,1,.3,1); }
.rail-track span:hover { color: #213a69; opacity: 1; transform: scale(1.06); }
.rail-track i { width: 9px; height: 9px; border-radius: 3px; background: linear-gradient(135deg, var(--home-blue), var(--home-cyan)); transform: rotate(12deg); transition: filter .2s ease, box-shadow .2s ease; }
.rail-track span:hover i { filter: saturate(1.35) brightness(.88); box-shadow: 0 3px 10px rgba(37,99,235,.22); }
@keyframes rail-forward { from { transform: translateX(-50%); } to { transform: translateX(0); } }

.overview-section { scroll-margin-top: 24px; }
.section-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 30px; margin-bottom: 28px; }
.section-heading h2, .workspace-copy h2, .architecture-copy h2, .overview-cta h2 { margin: 0; color: #1d2635; font-size: clamp(28px, 3vw, 38px); line-height: 1.28; }
.section-heading p, .workspace-copy > p, .architecture-copy > p, .overview-cta p { max-width: 720px; margin: 8px 0 0; color: #657188; font-size: 14px; line-height: 1.8; }
.section-heading > span { display: inline-flex; align-items: center; gap: 7px; padding: 8px 11px; border: 1px solid rgba(37,99,235,.15); border-radius: 10px; color: #2b5ec6; background: rgba(239,245,255,.72); font-size: 11px; white-space: nowrap; }
.capability-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
.capability-grid article { min-height: 210px; padding: 24px; border: 1px solid rgba(76,111,181,.13); border-radius: 18px; color: var(--home-blue); background: rgba(255,255,255,.68); box-shadow: 0 16px 40px rgba(51,84,148,.07); transition: transform .22s ease, box-shadow .22s ease; }
.capability-grid article:hover { transform: translateY(-4px); box-shadow: 0 22px 50px rgba(51,84,148,.12); }
.capability-grid .capability-primary { grid-column: span 2; grid-row: span 2; min-height: 434px; display: flex; flex-direction: column; justify-content: space-between; padding: 32px; color: #fff; background: linear-gradient(145deg, #235de2, #4a75ef); }
.capability-icon { width: 48px; height: 48px; display: grid; place-items: center; border: 1px solid rgba(255,255,255,.3); border-radius: 14px; background: rgba(255,255,255,.13); }
.capability-grid h3 { margin: 28px 0 9px; color: #1f2b3d; font-size: 17px; }
.capability-grid p { margin: 0; color: #647087; font-size: 12px; line-height: 1.8; }
.capability-primary h3 { margin-top: 20px; color: #fff; font-size: 27px; }
.capability-primary p { max-width: 560px; color: rgba(255,255,255,.82); font-size: 14px; }
.capability-primary ul { display: grid; gap: 10px; margin: 26px 0 0; padding: 20px 0 0; border-top: 1px solid rgba(255,255,255,.18); list-style: none; color: rgba(255,255,255,.88); font-size: 12px; }
.capability-primary li::before { content: ''; width: 6px; height: 6px; display: inline-block; margin-right: 9px; border-radius: 50%; background: #8ce2e9; vertical-align: 1px; }

.workflow-section { padding: 44px; border: 1px solid rgba(76,111,181,.12); border-radius: 22px; background: rgba(255,255,255,.58); box-shadow: 0 20px 60px rgba(51,84,148,.07); }
.workflow-line { position: relative; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 26px; margin-top: 36px; }
.workflow-line::before { content: ''; position: absolute; top: 21px; right: 9%; left: 9%; height: 1px; background: rgba(37,99,235,.18); }
.workflow-line article { position: relative; z-index: 1; }
.workflow-line b { width: 44px; height: 44px; display: grid; place-items: center; margin-bottom: 18px; border: 1px solid rgba(37,99,235,.2); border-radius: 50%; color: var(--home-blue); background: #f8fbff; font-size: 13px; }
.workflow-line h3 { margin: 0 0 7px; color: #263249; font-size: 14px; }
.workflow-line p { margin: 0; color: #6d788c; font-size: 11px; line-height: 1.75; }

.workspace-section { display: grid; grid-template-columns: minmax(300px, .65fr) minmax(500px, 1.35fr); align-items: center; gap: clamp(42px, 7vw, 90px); padding: 44px; border-radius: 24px; background: linear-gradient(135deg, rgba(226,248,249,.65), rgba(238,244,255,.76)); }
.workspace-tabs { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 24px; }
.workspace-tabs span { padding: 8px 11px; border-radius: 9px; color: #6d788c; background: rgba(255,255,255,.54); font-size: 11px; }
.workspace-tabs .active { color: #fff; background: var(--home-blue); }
.workspace-preview { overflow: hidden; border: 1px solid rgba(255,255,255,.88); border-radius: 18px; background: rgba(255,255,255,.78); box-shadow: 0 28px 68px rgba(42,75,140,.16); transform: perspective(1200px) rotateY(-3deg); }
.workspace-preview > header { height: 42px; display: flex; align-items: center; gap: 6px; padding: 0 14px; border-bottom: 1px solid rgba(64,91,144,.1); }
.workspace-preview > header span { width: 8px; height: 8px; border-radius: 50%; background: #d8e0ef; }
.workspace-preview > header strong { margin-left: 7px; color: #718099; font-size: 9px; }
.preview-body { height: 330px; display: grid; grid-template-columns: 92px minmax(0, 1fr); }
.preview-body > nav { display: grid; align-content: start; gap: 12px; padding: 20px 15px; background: rgba(235,241,253,.82); }
.preview-body > nav i { height: 11px; border-radius: 5px; background: #cfdaf0; }
.preview-body > nav i:nth-child(2) { background: #7f9cf0; }
.preview-body > main { min-width: 0; display: grid; grid-template-rows: 46px minmax(0, 1fr) 58px; padding: 0 20px; }
.preview-toolbar { width: 42%; height: 12px; align-self: center; border-radius: 6px; background: #d6def0; }
.preview-body section { display: grid; align-content: center; gap: 13px; padding: 12px 8%; border-block: 1px solid rgba(64,91,144,.08); }
.preview-message { width: 62%; height: 34px; border-radius: 10px; background: #e8eefb; }
.preview-message.short { width: 38%; }
.preview-message.user { width: 45%; justify-self: end; background: #607cf0; }
.preview-message.long { height: 54px; }
.preview-body footer { display: flex; align-items: center; gap: 10px; padding: 0; border: 0; }
.preview-body footer div { height: 28px; flex: 1; border: 1px solid #d7e0f2; border-radius: 9px; }
.preview-body footer button { width: 28px; height: 28px; border: 0; border-radius: 9px; background: var(--home-blue); }

.stats-section { padding: 46px; border: 1px solid rgba(76,111,181,.12); border-radius: 22px; background: rgba(255,255,255,.64); }
.stats-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border-top: 1px solid rgba(37,99,235,.13); }
.stats-grid article { display: grid; gap: 5px; padding: 30px 24px 6px; border-left: 1px solid rgba(37,99,235,.13); }
.stats-grid article:first-child { border-left: 0; }
.stats-grid strong { color: var(--home-blue); font-size: 40px; font-variant-numeric: tabular-nums; }
.stats-grid strong small { margin-left: 3px; font-size: 16px; }
.stats-grid span { color: #66738b; font-size: 11px; }

.architecture-section { display: grid; grid-template-columns: minmax(300px, .8fr) minmax(420px, 1.2fr); align-items: center; gap: 70px; }
.architecture-copy > svg { margin-bottom: 18px; color: var(--home-blue); }
.architecture-stack { display: grid; gap: 10px; }
.architecture-stack > div { display: grid; grid-template-columns: 100px minmax(0, 1fr); align-items: center; gap: 24px; min-height: 64px; padding: 0 20px; border: 1px solid rgba(76,111,181,.12); border-radius: 14px; background: rgba(255,255,255,.66); box-shadow: 0 12px 34px rgba(51,84,148,.06); }
.architecture-stack span { color: #708099; font-size: 11px; }
.architecture-stack strong { color: #29364b; font-size: 13px; }

.overview-cta { display: flex; align-items: center; justify-content: space-between; gap: 30px; padding: 38px 42px; border: 1px solid rgba(37,99,235,.18); border-radius: 22px; background: linear-gradient(135deg, rgba(232,241,255,.92), rgba(222,231,255,.92)); box-shadow: 0 22px 60px rgba(45,82,155,.09); }
.overview-cta > div > svg { margin-bottom: 12px; color: var(--home-blue); }
.overview-cta a { min-height: 46px; display: inline-flex; align-items: center; gap: 8px; padding: 0 18px; border-radius: 12px; color: #fff; background: var(--home-blue); font-size: 13px; font-weight: 650; white-space: nowrap; }
.overview-safety { display: flex; align-items: center; justify-content: center; gap: 7px; margin: -34px 0 0; color: #7b8799; font-size: 11px; }

@media (max-width: 1000px) {
  .overview-hero { grid-template-columns: 1fr; min-height: 0; }
  .hero-console { max-width: 680px; }
  .capability-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .workspace-section, .architecture-section { grid-template-columns: 1fr; }
  .workspace-preview { transform: none; }
}
@media (max-width: 760px) {
  .overview-page { gap: 52px; padding-top: 24px; }
  .overview-hero { padding: 34px 22px; border-radius: 20px; }
  .hero-copy h1 { font-size: clamp(34px, 10vw, 46px); }
  .technology-rail { grid-template-columns: 1fr; gap: 14px; }
  .section-heading { align-items: flex-start; flex-direction: column; }
  .capability-grid { grid-template-columns: 1fr; }
  .capability-grid .capability-primary { grid-column: auto; grid-row: auto; min-height: 370px; }
  .workflow-section, .workspace-section, .stats-section { padding: 28px 20px; }
  .workflow-line { grid-template-columns: 1fr 1fr; }
  .workflow-line::before { display: none; }
  .stats-grid { grid-template-columns: 1fr 1fr; }
  .stats-grid article:nth-child(3) { border-left: 0; }
  .preview-body { grid-template-columns: 66px minmax(0, 1fr); height: 290px; }
  .overview-cta { align-items: flex-start; flex-direction: column; padding: 30px 24px; }
}
@media (max-width: 520px) {
  .entry-actions { align-items: stretch; flex-direction: column; }
  .hero-points { display: grid; }
  .hero-console { padding: 14px; }
  .workflow-line { grid-template-columns: 1fr; }
  .stats-grid { grid-template-columns: 1fr; }
  .stats-grid article { border-left: 0; border-top: 1px solid rgba(37,99,235,.13); }
  .stats-grid article:first-child { border-top: 0; }
  .architecture-stack > div { grid-template-columns: 70px minmax(0, 1fr); gap: 14px; padding: 12px 14px; }
}
@media (prefers-reduced-motion: reduce) {
  [data-reveal] { opacity: 1; transform: none; }
  .rail-track { animation-play-state: paused; }
  .hero-copy h1 strong { animation: none; background-position: 45% center; }
}
</style>
