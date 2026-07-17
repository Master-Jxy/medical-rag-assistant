import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ChatView from '../src/views/ChatView.vue'

const api = vi.hoisted(() => ({
  createConversation: vi.fn(),
  deleteConversation: vi.fn(),
  getConversation: vi.fn(),
  listConversations: vi.fn(),
  stopConversationStream: vi.fn(),
  streamConversation: vi.fn(),
}))

vi.mock('../src/api/conversations.js', () => api)

const summaries = [
  { id: 'conversation-1', title: '第一段会话', message_count: 2 },
  { id: 'conversation-2', title: '第二段会话', message_count: 2 },
]

const details = {
  'conversation-1': {
    id: 'conversation-1',
    messages: [
      { id: 'message-1', role: 'user', content: '第一段问题', status: 'completed', sources: [] },
      {
        id: 'message-2',
        role: 'assistant',
        content: '第一段回答',
        status: 'completed',
        sources: [
          { id: 1, file_name: '来源一.txt', page: null, content: '第一条引用内容' },
          { id: 2, file_name: '来源二.txt', page: null, content: '第二条引用内容' },
          { id: 3, file_name: '来源三.txt', page: null, content: '第三条引用内容' },
          { id: 4, file_name: '来源四.txt', page: null, content: '第四条引用内容' },
        ],
      },
    ],
  },
  'conversation-2': {
    id: 'conversation-2',
    messages: [
      { id: 'message-3', role: 'user', content: '第二段问题', status: 'completed', sources: [] },
      { id: 'message-4', role: 'assistant', content: '第二段回答', status: 'completed', sources: [] },
    ],
  },
}

function mountChatView() {
  return mount(ChatView, {
    global: {
      stubs: {
        ElButton: {
          template: '<button v-bind="$attrs" @click="$emit(\'click\')"><slot /></button>',
        },
      },
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  api.listConversations.mockResolvedValue({ conversations: summaries.map((item) => ({ ...item })) })
  api.getConversation.mockImplementation(async (id) => structuredClone(details[id]))
  api.deleteConversation.mockResolvedValue({ message: '会话已删除' })
  api.stopConversationStream.mockResolvedValue({ status: 'stopping', message: '正在停止回答' })
})

describe('ChatView 会话交互', () => {
  it('每收到一个 SSE token 都立即更新页面内容', async () => {
    let streamHandlers
    let finishStream
    api.streamConversation.mockImplementation((_id, _question, handlers) => {
      streamHandlers = handlers
      return new Promise((resolve) => { finishStream = resolve })
    })

    const wrapper = mountChatView()
    await flushPromises()

    await wrapper.get('textarea').setValue('请详细回答')
    await wrapper.get('form').trigger('submit')
    await nextTick()

    expect(api.streamConversation).toHaveBeenCalledOnce()
    const streamOptions = api.streamConversation.mock.calls[0][2]
    expect(streamOptions.idempotencyKey).toMatch(/^[0-9a-f-]{36}$/)

    streamHandlers.onToken('第一块')
    await nextTick()
    expect(wrapper.text()).toContain('第一块')
    expect(wrapper.text()).not.toContain('第二块')

    streamHandlers.onToken('第二块')
    await nextTick()
    expect(wrapper.text()).toContain('第一块第二块')

    finishStream()
    await flushPromises()
  })

  it('生成冲突时显示友好提示并移除未开始的空回答', async () => {
    const error = new Error('当前会话正在生成回答，请等待完成后再试。')
    error.userMessage = '当前会话正在生成回答，请等待完成后再试。'
    error.errorCode = 'CONVERSATION_GENERATION_IN_PROGRESS'
    api.streamConversation.mockRejectedValue(error)

    const wrapper = mountChatView()
    await flushPromises()

    const bubbleCount = wrapper.findAll('[data-testid="message-bubble"]').length
    await wrapper.get('textarea').setValue('不要重复生成')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain(
      '当前会话正在生成回答，请等待完成后再试。',
    )
    expect(wrapper.findAll('[data-testid="message-bubble"]')).toHaveLength(bubbleCount + 1)
    expect(wrapper.text()).toContain('不要重复生成')
  })

  it('等待后端确认停止并收到 stopped 事件后才恢复发送', async () => {
    let streamHandlers
    let finishStream
    api.streamConversation.mockImplementation((_id, _question, handlers) => {
      streamHandlers = handlers
      return new Promise((resolve) => { finishStream = resolve })
    })

    const wrapper = mountChatView()
    await flushPromises()
    await wrapper.get('textarea').setValue('请生成一个较长回答')
    await wrapper.get('form').trigger('submit')
    await nextTick()

    streamHandlers.onToken('部分回答')
    await nextTick()
    const stopButton = wrapper.get('.composer-footer button')
    await stopButton.trigger('click')
    await flushPromises()

    const streamOptions = api.streamConversation.mock.calls[0][2]
    expect(api.stopConversationStream).toHaveBeenCalledWith(
      'conversation-1',
      streamOptions.idempotencyKey,
    )
    expect(wrapper.get('textarea').attributes('disabled')).toBeDefined()

    streamHandlers.onStopped({
      message: '已停止生成。',
      request_id: 'stopped-request',
      user_message_id: 'stopped-user-message',
      assistant_message_id: 'stopped-assistant-message',
    })
    finishStream()
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('已停止生成。')
    expect(wrapper.get('textarea').attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).toContain('请求标识：stopped-request')
  })

  it('切换历史会话后立即展示对应消息', async () => {
    const wrapper = mountChatView()
    await flushPromises()
    expect(wrapper.text()).toContain('第一段回答')

    await wrapper.get('[data-conversation-id="conversation-2"] [data-testid="conversation-main"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('第二段回答')
    expect(wrapper.text()).not.toContain('第一段回答')
  })

  it('引用来源默认整组收起，并可点击展开和再次收起', async () => {
    const wrapper = mountChatView()
    await flushPromises()

    const toggle = wrapper.get('[data-testid="sources-toggle"]')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(toggle.text()).toContain('引用来源 · 4')
    expect(wrapper.text()).not.toContain('来源一.txt')

    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.text()).toContain('来源一.txt')
    expect(wrapper.text()).toContain('来源四.txt')

    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(wrapper.text()).not.toContain('来源一.txt')
  })

  it('取消删除保留会话，确认删除当前会话后安全切换', async () => {
    const wrapper = mountChatView()
    await flushPromises()

    const deleteButton = wrapper.get('[data-conversation-id="conversation-1"] [data-testid="conversation-delete"]')
    await deleteButton.trigger('click')
    expect(wrapper.text()).toContain('确认删除会话？')

    const dialogButtons = wrapper.findAll('.delete-dialog button')
    expect(dialogButtons).toHaveLength(2)
    await dialogButtons[0].trigger('click')
    expect(wrapper.find('[data-conversation-id="conversation-1"]').exists()).toBe(true)

    await deleteButton.trigger('click')
    await wrapper.findAll('.delete-dialog button')[1].trigger('click')
    await flushPromises()

    expect(api.deleteConversation).toHaveBeenCalledWith('conversation-1')
    expect(wrapper.find('[data-conversation-id="conversation-1"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('第二段回答')
  })
})
