<script setup>
import { computed, onMounted, ref } from 'vue'
import { getHealth } from '../api/system'

const loading = ref(false)
const backendStatus = ref('unknown')
const errorMessage = ref('')

const statusText = computed(() => {
  if (loading.value) return '正在连接'
  if (backendStatus.value === 'ok') return '运行正常'
  if (backendStatus.value === 'error') return '连接失败'
  return '尚未检查'
})

async function checkBackend() {
  loading.value = true
  errorMessage.value = ''
  try {
    const data = await getHealth()
    backendStatus.value = data.status === 'ok' ? 'ok' : 'error'
  } catch {
    backendStatus.value = 'error'
    errorMessage.value = '无法连接 FastAPI，请确认后端已在 8000 端口启动。'
  } finally {
    loading.value = false
  }
}

onMounted(checkBackend)
</script>

<template>
  <section class="hero-section">
    <div class="eyebrow">MEDICAL KNOWLEDGE ASSISTANT</div>
    <h1>让每一次资料查询<br />都有来源可循</h1>
    <p class="hero-copy">
      基于 FastAPI、LangChain 与本地知识库构建的医疗资料检索助手。当前前后端基础链路已经接通。
    </p>

    <div class="status-card">
      <div class="status-icon" :class="backendStatus"><span></span></div>
      <div class="status-content">
        <span class="status-label">FastAPI 后端</span>
        <strong>{{ statusText }}</strong>
        <p v-if="errorMessage">{{ errorMessage }}</p>
        <p v-else>健康检查接口：GET /api/v1/health</p>
      </div>
      <el-button :loading="loading" plain round @click="checkBackend">重新检查</el-button>
    </div>

    <div class="feature-grid">
      <article><span>01</span><h2>资料有依据</h2><p>回答可展示使用的文件、页码与相关原文片段。</p></article>
      <article><span>02</span><h2>密钥不出后端</h2><p>浏览器只访问 FastAPI，不直接连接任何模型服务。</p></article>
      <article><span>03</span><h2>医疗边界明确</h2><p>用于学习与信息检索，不替代医生诊断和治疗建议。</p></article>
    </div>
  </section>
</template>

<style scoped>
.hero-section { padding: 88px 0 64px; }
.eyebrow { color: var(--primary); font-size: 12px; font-weight: 800; letter-spacing: .18em; }
h1 { max-width: 760px; margin: 20px 0 24px; color: var(--ink); font-size: clamp(42px, 6vw, 72px); line-height: 1.08; letter-spacing: -.055em; }
.hero-copy { max-width: 670px; color: var(--muted); font-size: 17px; line-height: 1.8; }
.status-card {
  margin-top: 48px; display: grid; grid-template-columns: auto 1fr auto; align-items: center;
  gap: 18px; padding: 22px 24px; border: 1px solid var(--line); border-radius: 18px;
  background: rgba(255, 255, 255, .88); box-shadow: 0 18px 45px rgba(35, 87, 77, .08);
}
.status-icon { width: 44px; height: 44px; display: grid; place-items: center; border-radius: 50%; background: #edf1f0; }
.status-icon span { width: 12px; height: 12px; border-radius: 50%; background: #91a09d; }
.status-icon.ok { background: #e3f5ee; }
.status-icon.ok span { background: #18a875; box-shadow: 0 0 0 6px rgba(24, 168, 117, .12); }
.status-icon.error { background: #fff0ed; }
.status-icon.error span { background: #dc5a42; }
.status-content span, .status-content strong { display: block; }
.status-label { margin-bottom: 3px; color: var(--muted); font-size: 12px; }
.status-content strong { font-size: 18px; }
.status-content p { margin: 5px 0 0; color: var(--muted); font-size: 13px; }
.feature-grid { margin-top: 24px; display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.feature-grid article { padding: 26px; border: 1px solid var(--line); border-radius: 16px; background: rgba(255, 255, 255, .58); }
.feature-grid span { color: var(--primary); font-size: 12px; font-weight: 800; }
.feature-grid h2 { margin: 22px 0 10px; font-size: 18px; }
.feature-grid p { margin: 0; color: var(--muted); font-size: 14px; line-height: 1.7; }
@media (max-width: 720px) {
  .hero-section { padding-top: 54px; }
  .status-card { grid-template-columns: auto 1fr; }
  .status-card .el-button { grid-column: 1 / -1; width: 100%; }
  .feature-grid { grid-template-columns: 1fr; }
}
</style>
