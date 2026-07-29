import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const authApi = vi.hoisted(() => ({
  confirmPasswordReset: vi.fn(),
  getCurrentUser: vi.fn(),
  loginUser: vi.fn(),
  registerUser: vi.fn(),
  requestEmailVerification: vi.fn(),
  requestPasswordReset: vi.fn(),
}))

vi.mock('../src/api/auth.js', () => authApi)

import router from '../src/router/index.js'
import { signOut } from '../src/auth/session.js'
import PasswordResetView from '../src/views/PasswordResetView.vue'

beforeEach(async () => {
  vi.clearAllMocks()
  signOut()
  window.localStorage.clear()
  authApi.requestPasswordReset.mockResolvedValue({
    message: '如果该邮箱已注册，验证码将发送到邮箱。',
  })
  authApi.confirmPasswordReset.mockResolvedValue({
    message: '密码已重置，请重新登录。',
  })
  await router.replace('/password-reset')
})

describe('忘记密码页面', () => {
  it('请求验证码始终展示后端统一提示', async () => {
    const wrapper = mount(PasswordResetView, { global: { plugins: [router] } })
    await wrapper.get('input[type="email"]').setValue('reset@example.com')
    await wrapper.get('.secondary-button').trigger('click')
    await flushPromises()

    expect(authApi.requestPasswordReset).toHaveBeenCalledWith({
      email: 'reset@example.com',
    })
    expect(wrapper.get('[role="status"]').text()).toBe(
      '如果该邮箱已注册，验证码将发送到邮箱。',
    )
  })

  it('重置成功清理登录状态并返回登录页', async () => {
    window.localStorage.setItem('medical-rag-access-token', 'old-token')
    const wrapper = mount(PasswordResetView, { global: { plugins: [router] } })
    const passwords = wrapper.findAll('input[type="password"]')
    await wrapper.get('input[type="email"]').setValue('reset@example.com')
    await wrapper.get('input[autocomplete="one-time-code"]').setValue('654321')
    await passwords[0].setValue('new-password')
    await passwords[1].setValue('new-password')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(authApi.confirmPasswordReset).toHaveBeenCalledWith({
      email: 'reset@example.com',
      verification_code: '654321',
      new_password: 'new-password',
    })
    expect(window.localStorage.getItem('medical-rag-access-token')).toBeNull()
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.reset).toBe('success')
  })

  it('长错误和请求ID一起显示而不暴露原始异常', async () => {
    authApi.requestPasswordReset.mockRejectedValue({
      response: {
        status: 503,
        data: {
          error: { code: 'EMAIL_VERIFICATION_UNAVAILABLE', message: '验证码服务暂时不可用，请稍后重试' },
          request_id: 'request-safe-123',
        },
      },
    })
    const wrapper = mount(PasswordResetView, { global: { plugins: [router] } })
    await wrapper.get('input[type="email"]').setValue('reset@example.com')
    await wrapper.get('.secondary-button').trigger('click')
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('验证码服务暂时不可用')
    expect(wrapper.get('[role="alert"]').text()).toContain('request-safe-123')
  })
})
