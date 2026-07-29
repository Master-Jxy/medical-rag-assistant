<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { confirmPasswordReset, requestPasswordReset } from '../api/auth.js'
import { getApiErrorMessage } from '../api/http.js'
import { signOut } from '../auth/session.js'

const router = useRouter()
const email = ref('')
const verificationCode = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const sending = ref(false)
const submitting = ref(false)
const requested = ref(false)
const errorMessage = ref('')
const statusMessage = ref('')

function displayError(error) {
  const message = getApiErrorMessage(error)
  const requestId = error?.requestId || error?.response?.data?.request_id
  errorMessage.value = requestId ? `${message}（请求 ID：${requestId}）` : message
}

async function requestCode() {
  if (sending.value) return
  errorMessage.value = ''
  statusMessage.value = ''
  sending.value = true
  try {
    const response = await requestPasswordReset({ email: email.value.trim() })
    requested.value = true
    statusMessage.value = response.message || '如果该邮箱已注册，验证码将发送到邮箱。'
  } catch (error) {
    displayError(error)
  } finally {
    sending.value = false
  }
}

async function submit() {
  if (submitting.value) return
  errorMessage.value = ''
  if (newPassword.value.length < 8) {
    errorMessage.value = '密码至少需要 8 个字符。'
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    errorMessage.value = '两次输入的密码不一致。'
    return
  }
  submitting.value = true
  try {
    await confirmPasswordReset({
      email: email.value.trim(),
      verification_code: verificationCode.value,
      new_password: newPassword.value,
    })
    signOut()
    await router.replace({ name: 'login', query: { reset: 'success' } })
  } catch (error) {
    displayError(error)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="reset-page">
    <div class="reset-card">
      <span class="eyebrow">ACCOUNT RECOVERY</span>
      <h1>重置密码</h1>
      <p>输入注册邮箱获取验证码。无论邮箱是否存在，系统都会使用相同提示。</p>
      <div v-if="errorMessage" class="reset-message error" role="alert">{{ errorMessage }}</div>
      <div v-if="statusMessage" class="reset-message success" role="status">{{ statusMessage }}</div>
      <form @submit.prevent="submit">
        <label>
          <span>邮箱</span>
          <input v-model="email" type="email" autocomplete="email" required placeholder="name@example.com" />
        </label>
        <button class="secondary-button" type="button" :disabled="sending" @click="requestCode">
          {{ sending ? '正在请求…' : requested ? '重新请求验证码' : '请求验证码' }}
        </button>
        <label>
          <span>验证码</span>
          <input v-model="verificationCode" inputmode="numeric" autocomplete="one-time-code" pattern="\d{6}" minlength="6" maxlength="6" required placeholder="6 位验证码" />
        </label>
        <label>
          <span>新密码</span>
          <input v-model="newPassword" type="password" autocomplete="new-password" minlength="8" maxlength="128" required placeholder="至少 8 个字符" />
        </label>
        <label>
          <span>确认新密码</span>
          <input v-model="confirmPassword" type="password" autocomplete="new-password" minlength="8" maxlength="128" required placeholder="再次输入新密码" />
        </label>
        <button class="primary-button" type="submit" :disabled="submitting">
          {{ submitting ? '正在重置…' : '确认重置密码' }}
        </button>
      </form>
      <router-link class="back-link" to="/login">返回登录</router-link>
    </div>
  </section>
</template>

<style scoped>
.reset-page { min-height: calc(100vh - 145px); display: grid; place-items: center; padding: 42px 0; }
.reset-card { width: min(100%, 460px); padding: 30px; border: 1px solid var(--line); border-radius: 8px; background: white; box-shadow: 0 20px 55px rgba(35,87,77,.1); }
.eyebrow { color: var(--primary); font-size: 11px; font-weight: 800; letter-spacing: .14em; }
h1 { margin: 10px 0 8px; font-size: 26px; }
p { margin: 0 0 20px; color: var(--muted); font-size: 13px; line-height: 1.65; }
form, label { display: grid; gap: 8px; }
form { gap: 15px; }
label { color: #36534d; font-size: 13px; font-weight: 700; }
input { width: 100%; padding: 12px 13px; border: 1px solid #ceddd8; border-radius: 7px; outline: none; background: #fbfdfc; }
input:focus { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(21,122,103,.1); }
.primary-button, .secondary-button { min-height: 42px; border-radius: 7px; font-weight: 700; cursor: pointer; }
.primary-button { border: 0; color: white; background: var(--primary); }
.secondary-button { border: 1px solid #b9cdc7; color: var(--primary-dark); background: white; }
button:disabled { cursor: wait; opacity: .65; }
.reset-message { margin-bottom: 15px; padding: 11px 13px; overflow-wrap: anywhere; border-radius: 7px; font-size: 13px; }
.reset-message.error { color: #a33f2f; background: #fff0ed; }
.reset-message.success { color: #176a58; background: #eaf8f2; }
.back-link { display: block; margin-top: 18px; color: var(--action); text-align: center; font-size: 13px; font-weight: 700; }
@media (max-width: 480px) { .reset-page { padding: 24px 0; } .reset-card { padding: 24px 18px; } }
</style>
