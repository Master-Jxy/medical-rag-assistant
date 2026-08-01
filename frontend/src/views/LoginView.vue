<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, HeartPulse, KeyRound, LockKeyhole, Mail, ShieldCheck, UserRound } from '@lucide/vue'

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
    <div class="auth-card">
      <header class="auth-brand">
        <span><HeartPulse :size="22" /></span>
        <div><strong>Medical RAG</strong><small>医疗知识库工作台</small></div>
      </header>
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
          <span class="input-shell"><UserRound :size="16" /><input v-model="displayName" autocomplete="name" maxlength="100" placeholder="如何称呼你" /></span>
        </label>
        <label>
          <span>邮箱</span>
          <span class="input-shell"><Mail :size="16" /><input v-model="email" type="email" autocomplete="email" required placeholder="name@example.com" /></span>
        </label>
        <label v-if="mode === 'register'">
          <span>邮箱验证码</span>
          <span class="verification-row">
            <span class="input-shell"><KeyRound :size="16" /><input
                v-model="verificationCode"
                inputmode="numeric"
                autocomplete="one-time-code"
                pattern="\d{6}"
                minlength="6"
                maxlength="6"
                required
                placeholder="6 位验证码"
              /></span>
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
          <span class="input-shell"><LockKeyhole :size="16" /><input v-model="password" type="password" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" required maxlength="128" :minlength="mode === 'register' ? 8 : 1" placeholder="输入密码" /></span>
        </label>
        <label v-if="mode === 'register'">
          <span>确认密码</span>
          <span class="input-shell"><LockKeyhole :size="16" /><input v-model="confirmPassword" type="password" autocomplete="new-password" required maxlength="128" minlength="8" placeholder="再次输入密码" /></span>
        </label>
        <button class="auth-submit" type="submit" :disabled="submitting">
          <span>{{ submitting ? '正在处理…' : submitText }}</span><ArrowRight v-if="!submitting" :size="16" />
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
      <footer class="auth-safety"><ShieldCheck :size="14" /><span>账号会话与用量按用户隔离保存</span></footer>
    </div>
  </section>
</template>

<style scoped>
.auth-page { min-height: calc(100vh - 166px); display: grid; place-items: center; padding: 36px 0; }
.auth-card { width: min(100%, 430px); padding: 24px; border: 1px solid var(--border-default); border-radius: 8px; background: var(--bg-surface); box-shadow: 0 18px 48px rgba(23, 32, 30, .1); }
.auth-brand { display: flex; align-items: center; gap: 10px; margin-bottom: 22px; }
.auth-brand > span { width: 38px; height: 38px; display: grid; place-items: center; border-radius: 7px; color: #fff; background: var(--brand); }
.auth-brand strong, .auth-brand small { display: block; }
.auth-brand strong { color: var(--text-strong); font-size: 14px; }
.auth-brand small { margin-top: 1px; color: var(--text-muted); font-size: 10px; }
.auth-tabs { display: grid; grid-template-columns: 1fr 1fr; gap: 3px; padding: 3px; border-radius: 7px; background: #eef2f1; }
.auth-tabs button { min-height: 34px; padding: 0 9px; border: 0; border-radius: 5px; color: var(--text-muted); background: transparent; cursor: pointer; }
.auth-tabs button.active { color: var(--text-strong); background: white; box-shadow: 0 1px 4px rgba(23,32,30,.1); font-weight: 600; }
.auth-card h2 { margin: 22px 0 5px; color: var(--text-strong); font-size: 20px; letter-spacing: 0; }
.auth-hint { margin: 0 0 22px; color: var(--muted); font-size: 13px; }
.auth-error, .auth-success { margin-bottom: 15px; padding: 10px 12px; overflow-wrap: anywhere; border: 1px solid transparent; border-radius: 6px; font-size: 12px; line-height: 19px; }
.auth-error { color: #982e2a; border-color: #efc3bf; background: #fff8f7; }
.auth-success { color: #176a4d; border-color: #badcca; background: #f4fbf7; }
form { display: grid; gap: 14px; }
label { display: grid; gap: 7px; color: #36534d; font-size: 13px; font-weight: 700; }
label small { color: var(--muted); font-weight: 400; }
.input-shell { min-height: 40px; display: flex; align-items: center; gap: 9px; padding: 0 11px; border: 1px solid var(--border-strong); border-radius: 6px; color: #82908c; background: var(--bg-surface); }
.input-shell:focus-within { border-color: var(--action); box-shadow: 0 0 0 3px rgba(37,99,235,.1); }
.input-shell input { min-width: 0; flex: 1; padding: 0; border: 0; outline: 0; color: var(--text-strong); background: transparent; font-weight: 400; }
.verification-row { display: grid; grid-template-columns: minmax(0, 1fr) 118px; gap: 8px; }
.verification-button { width: 118px; padding: 0 8px; border: 1px solid var(--border-strong); border-radius: 6px; color: var(--action); background: white; cursor: pointer; font-size: 12px; }
.verification-button:disabled { cursor: wait; opacity: .65; }
.auth-submit { min-height: 40px; display: flex; align-items: center; justify-content: center; gap: 7px; margin-top: 4px; padding: 0 13px; border: 0; border-radius: 6px; color: white; background: var(--action); font: inherit; font-weight: 600; cursor: pointer; }
.auth-submit:hover { background: var(--action-hover); }
.auth-submit:disabled { cursor: wait; opacity: .65; }
.auth-switch { margin: 17px 0 0; color: var(--muted); text-align: center; font-size: 12px; }
.auth-switch button { padding: 0; border: 0; color: var(--primary); background: transparent; font: inherit; font-weight: 700; cursor: pointer; }
.auth-forgot { margin-top: 8px; }
.auth-forgot a { color: var(--action); font-weight: 700; }
.auth-safety { display: flex; align-items: center; justify-content: center; gap: 6px; margin-top: 20px; padding-top: 15px; border-top: 1px solid var(--border-default); color: var(--text-muted); font-size: 10px; }
@media (max-width: 480px) { .auth-page { padding: 20px 0; } .auth-card { padding: 20px 16px; } .verification-row { grid-template-columns: minmax(0, 1fr) 104px; } .verification-button { width: 104px; } }
</style>
