import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const authApi = vi.hoisted(() => ({
  getCurrentUser: vi.fn(),
  loginUser: vi.fn(),
  registerUser: vi.fn(),
}))

vi.mock('../src/api/auth.js', () => authApi)

import router from '../src/router/index.js'
import { signOut, useAuthSession } from '../src/auth/session.js'
import { getAccessToken } from '../src/auth/token.js'
import LoginView from '../src/views/LoginView.vue'

const user = {
  id: 'user-1',
  email: 'learner@example.com',
  display_name: '学习者',
  is_active: true,
  role: 'user',
}

function mountLogin() {
  return mount(LoginView, { global: { plugins: [router] } })
}

beforeEach(async () => {
  vi.clearAllMocks()
  signOut()
  window.localStorage.clear()
  authApi.loginUser.mockResolvedValue({ access_token: 'test-token', token_type: 'bearer' })
  authApi.getCurrentUser.mockResolvedValue(user)
  authApi.registerUser.mockResolvedValue(user)
  await router.replace('/')
})

describe('前端认证流程', () => {
  it('未登录访问受保护页面会跳到登录页并保留原地址', async () => {
    await router.push('/knowledge?from=test')

    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/knowledge?from=test')
  })

  it('登录成功保存 Token、读取当前用户并返回原页面', async () => {
    await router.push('/login?redirect=/knowledge')
    const wrapper = mountLogin()

    await wrapper.get('input[type="email"]').setValue('LEARNER@example.com')
    await wrapper.get('input[type="password"]').setValue('password123')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(authApi.loginUser).toHaveBeenCalledWith({
      email: 'LEARNER@example.com',
      password: 'password123',
    })
    expect(authApi.getCurrentUser).toHaveBeenCalled()
    expect(getAccessToken()).toBe('test-token')
    expect(useAuthSession().user).toEqual(user)
    expect(router.currentRoute.value.fullPath).toBe('/knowledge')
  })

  it('注册时会在提交前拦截两次密码不一致', async () => {
    await router.push('/login')
    const wrapper = mountLogin()
    await wrapper.findAll('[role="tab"]')[1].trigger('click')

    const passwords = wrapper.findAll('input[type="password"]')
    await wrapper.get('input[type="email"]').setValue('new@example.com')
    await passwords[0].setValue('password123')
    await passwords[1].setValue('password456')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.get('[role="alert"]').text()).toContain('两次输入的密码不一致')
    expect(authApi.registerUser).not.toHaveBeenCalled()
  })

  it('普通用户不能进入管理员页面，数据库返回管理员角色后才能进入', async () => {
    useAuthSession().user = user
    await router.push('/admin/knowledge')
    expect(router.currentRoute.value.name).toBe('knowledge')

    useAuthSession().user = { ...user, role: 'admin' }
    await router.push('/admin/knowledge')
    expect(router.currentRoute.value.name).toBe('admin-knowledge')
  })
})
