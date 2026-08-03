import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ChatView from '../src/views/ChatView.vue'

const api = vi.hoisted(() => ({
  createConversation: vi.fn(),
  deleteConversation: vi.fn(),
  getConversation: vi.fn(),
  listConversations: vi.fn(),
  markConversationRead: vi.fn(),
  stopConversationStream: vi.fn(),
  streamConversation: vi.fn(),
}))
const modelApi = vi.hoisted(() => ({ getModelCatalog: vi.fn() }))

vi.mock('../src/api/conversations.js', () => api)
vi.mock('../src/api/models.js', () => modelApi)

const summaries = [
  { id: 'conversation-1', title: '第一段会话', message_count: 2, run_status: 'idle', has_unread: false, last_read_sequence: 0 },
  { id: 'conversation-2', title: '第二段会话', message_count: 2, run_status: 'idle', has_unread: false, last_read_sequence: 0 },
]

const details = {
  'conversation-1': {
    id: 'conversation-1',
    messages: [
      { id: 'message-1', sequence: 1, role: 'user', content: '第一段问题', status: 'completed', sources: [] },
      {
        id: 'message-2',
        sequence: 2,
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
      { id: 'message-3', sequence: 1, role: 'user', content: '第二段问题', status: 'completed', sources: [] },
      { id: 'message-4', sequence: 2, role: 'assistant', content: '第二段回答', status: 'completed', sources: [] },
    ],
  },
}

function mountChatView(options = {}) {
  return mount(ChatView, {
    ...options,
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
  modelApi.getModelCatalog.mockResolvedValue({
    active_model_id: 'qwen',
    options: [],
  })
  api.listConversations.mockResolvedValue({ conversations: summaries.map((item) => ({ ...item })) })
  api.getConversation.mockImplementation(async (id) => structuredClone(details[id]))
  api.deleteConversation.mockResolvedValue({ message: '会话已删除' })
  api.stopConversationStream.mockResolvedValue({ status: 'stopping', message: '正在停止回答' })
  api.markConversationRead.mockImplementation(async (id, lastReadSequence) => ({
    conversation_id: id,
    last_read_sequence: lastReadSequence,
  }))
})

describe('ChatView 会话交互', () => {
  it('仅把RAG助手回答渲染为安全Markdown', async () => {
    api.getConversation.mockResolvedValue({
      id: 'conversation-1',
      messages: [
        {
          id: 'markdown-user',
          role: 'user',
          content: '**用户原文**',
          status: 'completed',
          sources: [],
        },
        {
          id: 'markdown-assistant',
          role: 'assistant',
          content: '**回答重点**\n\n- 第一项\n- 第二项',
          status: 'completed',
          sources: [],
        },
      ],
    })

    const wrapper = mountChatView()
    await flushPromises()

    expect(wrapper.get('[data-testid="markdown-content"] strong').text()).toBe('回答重点')
    expect(wrapper.findAll('[data-testid="markdown-content"] li')).toHaveLength(2)
    expect(wrapper.text()).toContain('**用户原文**')
    expect(wrapper.findAll('strong').some((item) => item.text() === '用户原文')).toBe(false)
  })

  it('进入、切换、新建会话和回答结束后聚焦问题输入框', async () => {
    let finishStream
    api.streamConversation.mockImplementation(() => new Promise((resolve) => {
      finishStream = resolve
    }))
    api.createConversation.mockResolvedValue({
      id: 'conversation-3',
      title: '新会话',
      message_count: 0,
    })
    const host = document.createElement('div')
    document.body.appendChild(host)
    const wrapper = mountChatView({ attachTo: host })

    await flushPromises()
    expect(document.activeElement).toBe(wrapper.get('textarea').element)

    await wrapper.get('[data-conversation-id="conversation-2"] [data-testid="conversation-main"]').trigger('click')
    await flushPromises()
    expect(document.activeElement).toBe(wrapper.get('textarea').element)

    await wrapper.get('.new-chat-button').trigger('click')
    await flushPromises()
    expect(document.activeElement).toBe(wrapper.get('textarea').element)

    await wrapper.get('textarea').setValue('继续提问')
    await wrapper.get('form').trigger('submit')
    await nextTick()
    expect(wrapper.get('textarea').attributes('disabled')).toBeDefined()

    finishStream()
    await flushPromises()
    expect(document.activeElement).toBe(wrapper.get('textarea').element)

    wrapper.unmount()
    host.remove()
  })

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
    const stopButton = wrapper.get('[data-testid="stop-generation"]')
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

    const messageArea = wrapper.get('[data-testid="rag-message-area"]').element
    Object.defineProperty(messageArea, 'scrollHeight', {
      configurable: true,
      value: 4321,
    })
    messageArea.scrollTop = 0
    await wrapper.get('[data-conversation-id="conversation-2"] [data-testid="conversation-main"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('第二段回答')
    expect(wrapper.text()).not.toContain('第一段回答')
    expect(messageArea.scrollTop).toBe(4321)
    expect(messageArea.style.scrollBehavior).toBe('')
  })

  it('刷新后使用服务端active_run_id停止RAG回答', async () => {
    api.listConversations.mockResolvedValue({
      conversations: [{
        ...summaries[0],
        run_status: 'pending',
        active_run_id: 'request-from-server',
      }],
    })
    const wrapper = mountChatView()
    await flushPromises()

    const stop = wrapper.findAll('button').find((item) => item.text() === '停止生成')
    expect(stop).toBeTruthy()
    await stop.trigger('click')
    await flushPromises()

    expect(api.stopConversationStream).toHaveBeenCalledWith(
      'conversation-1',
      'request-from-server',
    )
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

  it('会话A后台生成时可新建并发送会话B，A完成后显示未读且不会写入B', async () => {
    const currentSummaries = summaries.map((item) => ({ ...item }))
    const currentDetails = structuredClone(details)
    const streams = {}
    api.listConversations.mockImplementation(async () => ({
      conversations: currentSummaries.map((item) => ({ ...item })),
    }))
    api.getConversation.mockImplementation(async (id) => structuredClone(currentDetails[id]))
    api.createConversation.mockImplementation(async () => {
      const summary = {
        id: 'conversation-3',
        title: '并发会话',
        message_count: 0,
        run_status: 'idle',
        has_unread: false,
        last_read_sequence: 0,
      }
      currentSummaries.unshift(summary)
      currentDetails[summary.id] = { ...summary, messages: [] }
      return { ...summary }
    })
    api.streamConversation.mockImplementation((id, _question, handlers) => new Promise((resolve) => {
      streams[id] = { handlers, resolve }
    }))

    const wrapper = mountChatView()
    await flushPromises()
    await wrapper.get('textarea').setValue('A的问题')
    await wrapper.get('form').trigger('submit')
    await nextTick()
    expect(wrapper.get('[data-conversation-id="conversation-1"] .conversation-spinner').exists()).toBe(true)

    await wrapper.get('.new-chat-button').trigger('click')
    await flushPromises()
    expect(wrapper.get('textarea').attributes('disabled')).toBeUndefined()
    await wrapper.get('textarea').setValue('B的问题')
    await wrapper.get('form').trigger('submit')
    await nextTick()

    expect(api.streamConversation.mock.calls.map((call) => call[0])).toEqual([
      'conversation-1',
      'conversation-3',
    ])
    expect(wrapper.get('[data-conversation-id="conversation-1"] .conversation-spinner').exists()).toBe(true)
    expect(wrapper.get('[data-conversation-id="conversation-3"] .conversation-spinner').exists()).toBe(true)

    currentDetails['conversation-1'].messages.push(
      { id: 'a-user-new', sequence: 3, role: 'user', content: 'A的问题', status: 'completed', sources: [] },
      { id: 'a-assistant-new', sequence: 4, role: 'assistant', content: 'A的后台回答', status: 'completed', sources: [] },
    )
    currentSummaries.find((item) => item.id === 'conversation-1').has_unread = true
    streams['conversation-1'].handlers.onDone({
      user_message_id: 'a-user-new',
      assistant_message_id: 'a-assistant-new',
      request_id: 'request-a',
    })
    streams['conversation-1'].resolve()
    await flushPromises()

    expect(wrapper.text()).not.toContain('A的后台回答')
    expect(wrapper.get('[data-conversation-id="conversation-1"] .conversation-unread').exists()).toBe(true)
    expect(wrapper.get('[data-conversation-id="conversation-3"] .conversation-spinner').exists()).toBe(true)

    await wrapper.get('[data-conversation-id="conversation-1"] [data-testid="conversation-main"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('A的后台回答')
    expect(wrapper.find('[data-conversation-id="conversation-1"] .conversation-unread').exists()).toBe(false)
    expect(api.markConversationRead).toHaveBeenCalledWith('conversation-1', 4)
    wrapper.unmount()
  })

  it('停止操作只作用于当前会话，切换不会中断其他流且卸载会清理控制器', async () => {
    const streams = {}
    api.streamConversation.mockImplementation((id, _question, handlers) => new Promise((resolve) => {
      streams[id] = { handlers, resolve }
    }))
    const wrapper = mountChatView()
    await flushPromises()

    await wrapper.get('textarea').setValue('A长回答')
    await wrapper.get('form').trigger('submit')
    await wrapper.get('[data-conversation-id="conversation-2"] [data-testid="conversation-main"]').trigger('click')
    await flushPromises()
    await wrapper.get('textarea').setValue('B长回答')
    await wrapper.get('form').trigger('submit')
    await nextTick()

    await wrapper.get('[data-conversation-id="conversation-1"] [data-testid="conversation-main"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="stop-generation"]').trigger('click')
    await wrapper.get('[data-conversation-id="conversation-2"] [data-testid="conversation-main"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="stop-generation"]').trigger('click')

    expect(api.stopConversationStream.mock.calls.map((call) => call[0])).toEqual([
      'conversation-1',
      'conversation-2',
    ])
    const signals = api.streamConversation.mock.calls.map((call) => call[2].signal)
    expect(signals.every((signal) => !signal.aborted)).toBe(true)
    wrapper.unmount()
    expect(signals.every((signal) => signal.aborted)).toBe(true)
  })

  it('刷新后使用服务端has_unread恢复未读点，打开会话后提交已读序号', async () => {
    api.listConversations.mockResolvedValue({
      conversations: summaries.map((item) => ({
        ...item,
        has_unread: item.id === 'conversation-2',
      })),
    })
    const wrapper = mountChatView()
    await flushPromises()

    expect(wrapper.get('[data-conversation-id="conversation-2"] .conversation-unread').exists()).toBe(true)
    await wrapper.get('[data-conversation-id="conversation-2"] [data-testid="conversation-main"]').trigger('click')
    await flushPromises()
    expect(api.markConversationRead).toHaveBeenCalledWith('conversation-2', 2)
    expect(wrapper.find('[data-conversation-id="conversation-2"] .conversation-unread').exists()).toBe(false)
  })
})
