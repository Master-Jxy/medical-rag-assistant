<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { getApiErrorMessage } from '../api/http.js'
import { requestEmailVerification } from '../api/auth.js'
import { signIn, signUp } from '../auth/session.js'

const route = useRoute()
const router = useRouter()
const mode = ref('login')
const email = ref('')
const displayName = ref('')
const password = ref('')
const confirmPassword = ref('')
const verificationCode = ref('')
const submitting = ref(false)
const sendingCode = ref(false)
const resendSeconds = ref(0)
const errorMessage = ref('')
const successMessage = ref(route.query.reset === 'success' ? '密码已重置，请使用新密码登录。' : '')
let countdownTimer = null

const title = computed(() => mode.value === 'login' ? '登录知识库' : '创建新账号')
const submitText = computed(() => mode.value === 'login' ? '登录' : '创建账号')

function switchMode(nextMode) {
  mode.value = nextMode
  errorMessage.value = ''
  successMessage.value = ''
  password.value = ''
  confirmPassword.value = ''
  verificationCode.value = ''
}

function stopCountdown() {
  if (countdownTimer !== null) window.clearInterval(countdownTimer)
  countdownTimer = null
}

function startCountdown(seconds = 60) {
  stopCountdown()
  resendSeconds.value = seconds
  countdownTimer = window.setInterval(() => {
    resendSeconds.value -= 1
    if (resendSeconds.value <= 0) stopCountdown()
  }, 1000)
}

function displayError(error) {
  const message = getApiErrorMessage(error)
  const requestId = error?.requestId || error?.response?.data?.request_id
  errorMessage.value = requestId ? `${message}（请求 ID：${requestId}）` : message
}

async function sendVerificationCode() {
  if (sendingCode.value || resendSeconds.value > 0) return
  errorMessage.value = ''
  successMessage.value = ''
  if (!email.value.trim()) {
    errorMessage.value = '请先输入邮箱。'
    return
  }
  sendingCode.value = true
  try {
    await requestEmailVerification({
      email: email.value.trim(),
      purpose: 'register',
    })
    successMessage.value = '如果该邮箱可用于注册，验证码将发送到邮箱。'
    startCountdown(60)
  } catch (error) {
    displayError(error)
  } finally {
    sendingCode.value = false
  }
}

function resolveRedirect() {
  const target = route.query.redirect
  return typeof target === 'string' && target.startsWith('/') && !target.startsWith('//')
    ? target
    : '/chat'
}

async function submit() {
  if (submitting.value) return
  errorMessage.value = ''
  successMessage.value = ''

  if (mode.value === 'register' && password.value.length < 8) {
    errorMessage.value = '密码至少需要 8 个字符。'
    return
  }
  if (mode.value === 'register' && password.value !== confirmPassword.value) {
    errorMessage.value = '两次输入的密码不一致。'
    return
  }

  submitting.value = true
  try {
    const credentials = { email: email.value.trim(), password: password.value }
    if (mode.value === 'register') {
      await signUp({
        ...credentials,
        display_name: displayName.value.trim() || null,
        verification_code: verificationCode.value,
      })
      switchMode('login')
      successMessage.value = '账号创建成功，请使用邮箱和密码登录。'
      return
    } else {
      await signIn(credentials)
    }
    await router.replace(resolveRedirect())
  } catch (error) {
    displayError(error)
  } finally {
    submitting.value = false
  }
}

onBeforeUnmount(stopCountdown)
</script>

<template>
  <section class="auth-page">
    <div class="auth-intro">
      <span>ACCOUNT ACCESS</span>
      <h1>让知识与会话<br />都属于你自己</h1>
      <p>登录后可以访问公共医学资料，并安全保存只属于当前账号的问答历史。</p>
      <ul>
        <li>所有账号共享可检索的公共知识库</li>
        <li>聊天记录按账号严格隔离</li>
        <li>只有上传者可以删除自己的资料</li>
      </ul>
    </div>

    <div class="auth-card">
      <div class="auth-tabs" role="tablist" aria-label="账号操作">
        <button :class="{ active: mode === 'login' }" role="tab" :aria-selected="mode === 'login'" @click="switchMode('login')">登录</button>
        <button :class="{ active: mode === 'register' }" role="tab" :aria-selected="mode === 'register'" @click="switchMode('register')">注册</button>
      </div>

      <h2>{{ title }}</h2>
      <p class="auth-hint">{{ mode === 'login' ? '欢迎回来，请输入账号信息。' : '验证邮箱后创建账号。' }}</p>

      <div v-if="errorMessage" class="auth-error" role="alert">{{ errorMessage }}</div>
      <div v-if="successMessage" class="auth-success" role="status">{{ successMessage }}</div>

      <form @submit.prevent="submit">
        <label v-if="mode === 'register'">
          <span>昵称 <small>选填</small></span>
          <input v-model="displayName" autocomplete="name" maxlength="100" placeholder="如何称呼你" />
        </label>
        <label>
          <span>邮箱</span>
          <input v-model="email" type="email" autocomplete="email" required placeholder="name@example.com" />
        </label>
        <label v-if="mode === 'register'">
          <span>邮箱验证码</span>
          <span class="verification-row">
            <input
              v-model="verificationCode"
              inputmode="numeric"
              autocomplete="one-time-code"
              pattern="\d{6}"
              minlength="6"
              maxlength="6"
              required
              placeholder="6 位验证码"
            />
            <button
              class="verification-button"
              type="button"
              :disabled="sendingCode || resendSeconds > 0"
              @click="sendVerificationCode"
            >
              {{ sendingCode ? '发送中…' : resendSeconds > 0 ? `${resendSeconds} 秒` : '发送验证码' }}
            </button>
          </span>
        </label>
        <label>
          <span>密码</span>
          <input v-model="password" type="password" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" required maxlength="128" :minlength="mode === 'register' ? 8 : 1" placeholder="输入密码" />
        </label>
        <label v-if="mode === 'register'">
          <span>确认密码</span>
          <input v-model="confirmPassword" type="password" autocomplete="new-password" required maxlength="128" minlength="8" placeholder="再次输入密码" />
        </label>
        <button class="auth-submit" type="submit" :disabled="submitting">
          {{ submitting ? '正在处理…' : submitText }}
        </button>
      </form>

      <p class="auth-switch">
        {{ mode === 'login' ? '还没有账号？' : '已经有账号？' }}
        <button @click="switchMode(mode === 'login' ? 'register' : 'login')">
          {{ mode === 'login' ? '立即注册' : '返回登录' }}
        </button>
      </p>
      <p v-if="mode === 'login'" class="auth-switch auth-forgot">
        <router-link to="/password-reset">忘记密码？</router-link>
      </p>
    </div>
  </section>
</template>

<style scoped>
.auth-page { min-height: calc(100vh - 145px); display: grid; grid-template-columns: minmax(0, 1fr) minmax(360px, 440px); align-items: center; gap: clamp(48px, 8vw, 110px); padding: 58px 0; }
.auth-intro > span { color: var(--primary); font-size: 11px; font-weight: 800; letter-spacing: .18em; }
.auth-intro h1 { margin: 18px 0 20px; font-size: clamp(38px, 5vw, 60px); line-height: 1.12; letter-spacing: -.05em; }
.auth-intro p { max-width: 570px; color: var(--muted); line-height: 1.8; }
.auth-intro ul { display: grid; gap: 12px; margin: 28px 0 0; padding: 0; list-style: none; }
.auth-intro li { display: flex; gap: 10px; color: #3f5f58; font-size: 14px; }
.auth-intro li::before { content: '✓'; color: var(--primary); font-weight: 800; }
.auth-card { padding: 32px; border: 1px solid var(--line); border-radius: 24px; background: rgba(255,255,255,.94); box-shadow: 0 28px 70px rgba(35,87,77,.12); }
.auth-tabs { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; padding: 4px; border-radius: 12px; background: #eef4f2; }
.auth-tabs button { padding: 9px; border: 0; border-radius: 9px; color: var(--muted); background: transparent; cursor: pointer; }
.auth-tabs button.active { color: var(--primary-dark); background: white; box-shadow: 0 3px 10px rgba(35,87,77,.08); font-weight: 700; }
.auth-card h2 { margin: 26px 0 6px; font-size: 25px; }
.auth-hint { margin: 0 0 22px; color: var(--muted); font-size: 13px; }
.auth-error, .auth-success { margin-bottom: 16px; padding: 11px 13px; overflow-wrap: anywhere; border-radius: 8px; font-size: 13px; }
.auth-error { color: #a33f2f; background: #fff0ed; }
.auth-success { color: #176a58; background: #eaf8f2; }
form { display: grid; gap: 16px; }
label { display: grid; gap: 7px; color: #36534d; font-size: 13px; font-weight: 700; }
label small { color: var(--muted); font-weight: 400; }
input { width: 100%; padding: 12px 13px; border: 1px solid #ceddd8; border-radius: 11px; outline: none; color: var(--ink); background: #fbfdfc; font: inherit; font-weight: 400; }
input:focus { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(21,122,103,.1); }
.verification-row { display: grid; grid-template-columns: minmax(0, 1fr) 116px; gap: 8px; }
.verification-button { width: 116px; padding: 0 8px; border: 1px solid #b9cdc7; border-radius: 8px; color: var(--primary-dark); background: white; cursor: pointer; font-size: 12px; }
.verification-button:disabled { cursor: wait; opacity: .65; }
.auth-submit { margin-top: 5px; padding: 12px; border: 0; border-radius: 11px; color: white; background: var(--primary); font: inherit; font-weight: 700; cursor: pointer; }
.auth-submit:disabled { cursor: wait; opacity: .65; }
.auth-switch { margin: 20px 0 0; color: var(--muted); text-align: center; font-size: 13px; }
.auth-switch button { padding: 0; border: 0; color: var(--primary); background: transparent; font: inherit; font-weight: 700; cursor: pointer; }
.auth-forgot { margin-top: 10px; }
.auth-forgot a { color: var(--action); font-weight: 700; }
@media (max-width: 800px) { .auth-page { grid-template-columns: 1fr; gap: 34px; padding: 38px 0; } .auth-intro h1 { font-size: 40px; } }
@media (max-width: 480px) { .auth-card { padding: 24px 20px; } .verification-row { grid-template-columns: minmax(0, 1fr) 108px; } .verification-button { width: 108px; } }
</style>
