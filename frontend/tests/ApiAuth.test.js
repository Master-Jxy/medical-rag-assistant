import { beforeEach, describe, expect, it, vi } from 'vitest'

import { streamConversation } from '../src/api/conversations.js'
import http from '../src/api/http.js'
import { getAccessToken, setAccessToken } from '../src/auth/token.js'

beforeEach(() => {
  window.localStorage.clear()
  vi.restoreAllMocks()
})

describe('认证请求头和 401 处理', () => {
  it('Axios 请求自动附带 Bearer Token', async () => {
    setAccessToken('axios-token')
    let requestConfig
    const originalAdapter = http.defaults.adapter
    http.defaults.adapter = async (config) => {
      requestConfig = config
      return { data: {}, status: 200, statusText: 'OK', headers: {}, config }
    }

    try {
      await http.get('/auth-check')
      expect(requestConfig.headers.Authorization).toBe('Bearer axios-token')
    } finally {
      http.defaults.adapter = originalAdapter
    }
  })

  it('SSE 请求附带 Token，并在 401 后清除失效凭据', async () => {
    setAccessToken('stream-token')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(
      JSON.stringify({ error: { message: '登录状态已失效' } }),
      { status: 401, headers: { 'Content-Type': 'application/json' } },
    ))

    await expect(streamConversation('conversation-1', '问题')).rejects.toThrow('登录状态已失效')

    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer stream-token')
    expect(fetchMock.mock.calls[0][1].headers['Idempotency-Key']).toMatch(/^[0-9a-f-]{36}$/)
    expect(getAccessToken()).toBe('')
  })
})
