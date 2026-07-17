import { beforeEach, describe, expect, it, vi } from 'vitest'

const authApi = vi.hoisted(() => ({
  getCurrentUser: vi.fn(),
  loginUser: vi.fn(),
  registerUser: vi.fn(),
}))

vi.mock('../src/api/auth.js', () => authApi)

describe('刷新后的登录恢复', () => {
  beforeEach(() => {
    window.localStorage.clear()
    authApi.getCurrentUser.mockReset()
  })

  it('存在 Token 时通过 /auth/me 恢复当前用户', async () => {
    const user = { id: 'user-restore', email: 'restore@example.com', display_name: null }
    window.localStorage.setItem('medical-rag-access-token', 'persisted-token')
    authApi.getCurrentUser.mockResolvedValue(user)

    const { initializeAuth, useAuthSession } = await import('../src/auth/session.js')
    await initializeAuth()

    expect(authApi.getCurrentUser).toHaveBeenCalledOnce()
    expect(useAuthSession().user).toEqual(user)
  })
})
