import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ChatView from '../src/views/ChatView.vue'

const api = vi.hoisted(() => ({
  createConversation: vi.fn(),
  deleteConversation: vi.fn(),
  getConversation: vi.fn(),
  listConversations: vi.fn(),
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
      { id: 'message-2', role: 'assistant', content: '第一段回答', status: 'completed', sources: [] },
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

  it('切换历史会话后立即展示对应消息', async () => {
    const wrapper = mountChatView()
    await flushPromises()
    expect(wrapper.text()).toContain('第一段回答')

    await wrapper.get('[data-conversation-id="conversation-2"] [data-testid="conversation-main"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('第二段回答')
    expect(wrapper.text()).not.toContain('第一段回答')
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
