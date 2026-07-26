import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const agentApi = vi.hoisted(() => ({
  createAgentThread: vi.fn(),
  deleteAgentThread: vi.fn(),
  downloadAgentArtifact: vi.fn(),
  getAgentRun: vi.fn(),
  listAgentMessages: vi.fn(),
  listAgentRuns: vi.fn(),
  listAgentThreads: vi.fn(),
  retryAgentMessage: vi.fn(),
  stopAgentRun: vi.fn(),
  streamAgentMessage: vi.fn(),
  updateAgentThread: vi.fn(),
}))
const citationApi = vi.hoisted(() => ({
  getDocumentTrace: vi.fn(),
  openDocumentPreview: vi.fn(),
}))
vi.mock('../src/api/agent.js', () => agentApi)
vi.mock('../src/api/citations.js', () => citationApi)

import AgentView from '../src/views/AgentView.vue'
import {
  initialAgentStreamState,
  reduceAgentEvent,
} from '../src/features/agent-chat/agentEventReducer.js'

const thread = {
  id: 'thread-1',
  title: '患者安全',
  status: 'active',
  summary: null,
  summary_until_message_id: null,
  last_message_at: '2026-07-26T00:00:00Z',
  created_at: '2026-07-26T00:00:00Z',
  updated_at: '2026-07-26T00:00:00Z',
}
const archivedThread = {
  ...thread,
  id: 'thread-archived',
  title: '已归档患者安全',
  status: 'archived',
}
const run = {
  id: 'run-1',
  thread_id: 'thread-1',
  task: '生成患者安全报告',
  status: 'completed',
  step_count: 1,
  max_steps: 5,
  used_tokens: 25,
  estimated_cost_cny: 0.002,
  final_result: '学习报告已完成。',
  steps: [{
    id: 'step-1',
    sequence: 1,
    tool_name: 'generate_learning_report',
    status: 'completed',
    result_summary: '报告已生成',
  }],
  artifacts: [{ id: 'artifact-1', file_name: '学习报告.md' }],
}
const messages = [{
  id: 'message-user',
  thread_id: 'thread-1',
  role: 'user',
  content: '生成患者安全报告',
  status: 'completed',
  run_id: null,
  metadata: {},
}, {
  id: 'message-assistant',
  thread_id: 'thread-1',
  role: 'assistant',
  content: '学习报告已完成。',
  status: 'completed',
  run_id: 'run-1',
  metadata: { source_ids: ['doc-1'], artifact_ids: ['artifact-1'] },
}]

function mountView() {
  return mount(AgentView, {
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
  agentApi.listAgentThreads.mockImplementation(async (status) => ({
    items: status === 'archived' ? [archivedThread] : [thread],
  }))
  agentApi.listAgentMessages.mockResolvedValue({ items: messages })
  agentApi.listAgentRuns.mockResolvedValue({ items: [run] })
  agentApi.getAgentRun.mockResolvedValue(run)
  agentApi.updateAgentThread.mockImplementation(async (_id, changes) => ({
    ...thread,
    ...changes,
  }))
  agentApi.stopAgentRun.mockResolvedValue({ status: 'stopping' })
  citationApi.getDocumentTrace.mockResolvedValue({
    document_id: 'doc-1',
    file_name: '患者安全.pdf',
    version: 1,
  })
})

describe('Codex式资料Agent工作台', () => {
  it('展示会话、连续消息、步骤、来源和产物', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('AGENT CHAT V3')
    expect(wrapper.text()).toContain('患者安全')
    expect(wrapper.text()).toContain('学习报告已完成')
    expect(wrapper.text()).toContain('generate_learning_report')
    expect(wrapper.text()).toContain('来源 doc-1')
    expect(wrapper.text()).toContain('学习报告.md')
  })

  it('发送消息时使用会话SSE并在完成后恢复服务端状态', async () => {
    agentApi.streamAgentMessage.mockImplementation(
      async (_threadId, _payload, _key, handlers) => {
        handlers.onEvent('message_created', {
          assistant_message_id: 'message-new-assistant',
          run_id: 'run-new',
        })
        handlers.onEvent('plan_ready', { plan: ['检索资料'] })
        handlers.onEvent('tool_started', { tool_name: 'search_knowledge', step: 1 })
        handlers.onEvent('tool_completed', {
          tool_name: 'search_knowledge',
          status: 'completed',
          summary: '检索到2份资料',
        })
        handlers.onEvent('token', { content: '整理完成。' })
        handlers.onEvent('message_completed', {
          message_id: 'message-new-assistant',
          status: 'completed',
        })
      },
    )
    const wrapper = mountView()
    await flushPromises()
    await wrapper.get('textarea').setValue('继续整理')
    await wrapper.get('form.composer').trigger('submit')
    await flushPromises()

    expect(agentApi.streamAgentMessage).toHaveBeenCalledWith(
      'thread-1',
      expect.objectContaining({ content: '继续整理' }),
      expect.any(String),
      expect.any(Object),
    )
    expect(agentApi.listAgentMessages).toHaveBeenCalledTimes(2)
  })

  it('把用户选中的消息、来源和产物作为显式引用发送', async () => {
    agentApi.streamAgentMessage.mockResolvedValue()
    const wrapper = mountView()
    await flushPromises()

    const referenceButtons = wrapper.findAll('button').filter(
      (item) => item.text() === '引用此消息',
    )
    await referenceButtons[0].trigger('click')
    const sourceButton = wrapper.findAll('button').find(
      (item) => item.text() === '来源 doc-1',
    )
    await sourceButton.trigger('click')
    await flushPromises()
    const contextReferenceButtons = wrapper.findAll('button').filter(
      (item) => item.text() === '引用',
    )
    await contextReferenceButtons[0].trigger('click')
    await contextReferenceButtons[1].trigger('click')
    await wrapper.get('textarea').setValue('基于这些内容继续整理')
    await wrapper.get('form.composer').trigger('submit')
    await flushPromises()

    expect(agentApi.streamAgentMessage).toHaveBeenCalledWith(
      'thread-1',
      expect.objectContaining({
        content: '基于这些内容继续整理',
        referenced_message_ids: ['message-user'],
        source_ids: ['doc-1'],
        artifact_ids: ['artifact-1'],
      }),
      expect.any(String),
      expect.any(Object),
    )
  })

  it('可以查看已归档会话并恢复到进行中', async () => {
    const wrapper = mountView()
    await flushPromises()

    const archivedButton = wrapper.findAll('button').find(
      (item) => item.text() === '已归档',
    )
    await archivedButton.trigger('click')
    await flushPromises()

    expect(agentApi.listAgentThreads).toHaveBeenLastCalledWith('archived')
    expect(wrapper.text()).toContain('已归档患者安全')

    const restoreButton = wrapper.findAll('button').find(
      (item) => item.text() === '恢复',
    )
    await restoreButton.trigger('click')
    await flushPromises()

    expect(agentApi.updateAgentThread).toHaveBeenCalledWith(
      'thread-archived',
      { status: 'active' },
    )
    expect(wrapper.text()).not.toContain('已归档患者安全')
  })

  it('独立Reducer维护公开计划、工具、来源和结果，不接收隐藏推理', () => {
    let state = initialAgentStreamState()
    state = reduceAgentEvent(state, 'plan_ready', { plan: ['检索资料'] })
    state = reduceAgentEvent(state, 'tool_started', {
      tool_name: 'search_knowledge',
      step: 1,
    })
    state = reduceAgentEvent(state, 'sources', {
      source_ids: ['doc-1'],
      items: [{ document_id: 'doc-1', page: 3 }],
    })
    state = reduceAgentEvent(state, 'token', { content: '完成' })

    expect(state.plan).toEqual(['检索资料'])
    expect(state.steps[0].tool_name).toBe('search_knowledge')
    expect(state.sources[0].page).toBe(3)
    expect(state.output).toBe('完成')
    expect(state).not.toHaveProperty('chain_of_thought')
  })
})
