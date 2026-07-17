import { beforeEach, describe, expect, it, vi } from 'vitest'

import { streamConversation } from '../src/api/conversations.js'
import { consumeSseResponse } from '../src/api/chat.js'
import { getApiErrorMessage } from '../src/api/http.js'

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('Redis 保护错误提示', () => {
  it.each([
    ['CHAT_RATE_LIMITED', 429, '提问过于频繁，请稍后再试。'],
    ['CONVERSATION_GENERATION_IN_PROGRESS', 409, '当前会话正在生成回答，请等待完成后再试。'],
    ['IDEMPOTENCY_REQUEST_IN_PROGRESS', 409, '这次提问仍在处理中，请稍候，不要重复发送。'],
    ['IDEMPOTENCY_KEY_REUSED', 409, '请求状态已经变化，请重新发送这条问题。'],
    ['GENERATION_LOCK_UNAVAILABLE', 503, '问答保护服务暂时不可用，请稍后重试。'],
    ['IDEMPOTENCY_UNAVAILABLE', 503, '问答保护服务暂时不可用，请稍后重试。'],
  ])('SSE %s 返回稳定且非技术化的提示', async (code, status, expected) => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(
      JSON.stringify({
        error: { code, message: '后端原始说明' },
        request_id: 'request-safe-id',
      }),
      { status, headers: { 'Content-Type': 'application/json' } },
    ))

    let captured
    try {
      await streamConversation('conversation-1', '问题', { idempotencyKey: 'request-key' })
    } catch (error) {
      captured = error
    }

    expect(captured.userMessage).toBe(expected)
    expect(captured.errorCode).toBe(code)
    expect(captured.requestId).toBe('request-safe-id')
    expect(captured.status).toBe(status)
  })

  it.each([
    ['AUTH_RATE_LIMITED', 429, '登录尝试过于频繁，请稍后再试。'],
    ['UPLOAD_RATE_LIMITED', 429, '上传过于频繁，请稍后再试。'],
    ['UPLOAD_CONCURRENCY_LIMITED', 429, '当前已有文件正在处理，请等待完成后再上传。'],
  ])('普通请求 %s 使用同一套提示', (code, status, expected) => {
    const error = {
      response: {
        status,
        data: { error: { code, message: '后端原始说明' } },
      },
    }

    expect(getApiErrorMessage(error)).toBe(expected)
  })

  it('未知错误码仍保留后端的安全业务提示', () => {
    const error = {
      response: {
        status: 409,
        data: { error: { code: 'DOCUMENT_BUSY', message: '文档正在处理中' } },
      },
    }

    expect(getApiErrorMessage(error)).toBe('文档正在处理中')
  })

  it('停止生成时主动取消 SSE 读取器并返回停止状态', async () => {
    const controller = new AbortController()
    let finishRead
    const reader = {
      read: vi.fn(() => new Promise((resolve) => { finishRead = resolve })),
      cancel: vi.fn(async () => finishRead({ done: true })),
    }
    const response = { body: { getReader: () => reader } }
    const consuming = consumeSseResponse(response, { signal: controller.signal })

    controller.abort()

    await expect(consuming).rejects.toMatchObject({ name: 'AbortError' })
    expect(reader.cancel).toHaveBeenCalledOnce()
    expect(getApiErrorMessage(await consuming.catch((error) => error))).toBe('已停止生成。')
  })
})
