import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const agentApi = vi.hoisted(() => ({
  createAgentThread: vi.fn(),
  deleteAgentThread: vi.fn(),
  downloadAgentArtifact: vi.fn(),
  getAgentRun: vi.fn(),
  listAgentMessages: vi.fn(),
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
import AgentRunProgress from '../src/features/agent-chat/AgentRunProgress.vue'
import {
  initialAgentStreamState,
  reduceAgentEvent,
} from '../src/features/agent-chat/agentEventReducer.js'
import {
  createAgentTimelineState,
  reduceAgentTimeline,
} from '../src/features/agent-chat/useAgentTimeline.js'

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
  token_measurement: 'actual',
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
  sequence_no: 1,
  turn_id: 'turn-1',
  thread_id: 'thread-1',
  role: 'user',
  content: '生成患者安全报告',
  status: 'completed',
  run_id: null,
  metadata: {},
}, {
  id: 'message-assistant',
  sequence_no: 2,
  turn_id: 'turn-1',
  thread_id: 'thread-1',
  role: 'assistant',
  content: '学习报告已完成。',
  status: 'completed',
  run_id: 'run-1',
  metadata: {
    source_ids: ['doc-1'],
    sources: [{ document_id: 'doc-1', file_name: '患者安全.pdf' }],
    artifact_ids: ['artifact-1'],
  },
}]

function mountView(options = {}) {
  return mount(AgentView, {
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
  agentApi.listAgentThreads.mockImplementation(async (status) => ({
    items: status === 'archived' ? [archivedThread] : [thread],
  }))
  agentApi.listAgentMessages.mockResolvedValue({ items: messages })
  agentApi.getAgentRun.mockResolvedValue(run)
  agentApi.createAgentThread.mockResolvedValue({
    ...thread,
    id: 'thread-new',
    title: '新对话',
  })
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
  it('仅把Agent助手回答渲染为安全Markdown并使用统一名称', async () => {
    agentApi.listAgentMessages.mockResolvedValue({
      items: [{
        ...messages[0],
        content: '**用户原文**',
      }, {
        ...messages[1],
        content: '**Agent重点**\n\n- 已完成整理',
      }],
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.get('[data-testid="markdown-content"] strong').text()).toBe('Agent重点')
    expect(wrapper.get('[data-testid="markdown-content"] li').text()).toBe('已完成整理')
    expect(wrapper.text()).toContain('**用户原文**')
    expect(wrapper.text()).not.toContain('资料整理 Agent')
    expect(wrapper.text()).not.toContain('资料 Agent')
  })

  it('零工具失败任务不会伪装成成功的直接回答', () => {
    const wrapper = mount(AgentRunProgress, {
      props: {
        run: {
          status: 'failed',
          used_tokens: 0,
          estimated_cost_cny: 0,
          steps: [],
        },
        status: 'failed',
      },
    })

    expect(wrapper.text()).toContain('处理失败 · 0 次工具调用')
    expect(wrapper.text()).toContain('任务未完成')
    expect(wrapper.text()).toContain('任务在形成有效回答前失败，请重试')
    expect(wrapper.text()).not.toContain('该任务无需调用工具，已直接形成回答')
  })

  it('Agent缺少厂商usage时不把0展示成实际Token', () => {
    const wrapper = mount(AgentRunProgress, {
      props: {
        run: {
          status: 'completed',
          used_tokens: 0,
          estimated_cost_cny: 0,
          token_measurement: 'unknown',
          steps: [],
        },
        status: 'completed',
      },
    })

    expect(wrapper.text()).toContain('模型未返回计量')
    expect(wrapper.text()).toContain('预估费用 未知')
  })

  it('展示会话、连续消息、步骤、来源和产物', async () => {
    const wrapper = mountView()
    const messageArea = wrapper.get('[data-testid="agent-message-area"]').element
    Object.defineProperty(messageArea, 'scrollHeight', {
      configurable: true,
      value: 6789,
    })
    messageArea.scrollTop = 0
    await flushPromises()

    expect(wrapper.text()).toContain('AGENT CHAT V3')
    expect(wrapper.text()).toContain('患者安全')
    expect(wrapper.text()).toContain('学习报告已完成')
    expect(wrapper.text()).toContain('生成学习报告')
    const partToggles = wrapper.findAll('.parts-toggle')
    await partToggles[0].trigger('click')
    await partToggles[1].trigger('click')
    expect(wrapper.text()).toContain('患者安全.pdf')
    expect(wrapper.text()).toContain('学习报告.md')
    expect(messageArea.scrollTop).toBe(6789)
    expect(messageArea.style.scrollBehavior).toBe('')
  })

  it('发送消息时使用会话SSE并在完成后恢复服务端状态', async () => {
    agentApi.streamAgentMessage.mockImplementation(
      async (_threadId, _payload, _key, handlers) => {
        handlers.onEvent('message_created', {
          user_message_id: 'message-new-user',
          assistant_message_id: 'message-new-assistant',
          run_id: 'run-new',
          user_sequence_no: 3,
          assistant_sequence_no: 4,
          turn_id: 'turn-2',
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

  it('新建、切换会话和模型回复结束后自动聚焦输入框', async () => {
    agentApi.streamAgentMessage.mockImplementation(
      async (_threadId, _payload, _key, handlers) => {
        handlers.onEvent('message_created', {
          user_message_id: 'focus-user',
          assistant_message_id: 'focus-assistant',
          run_id: 'focus-run',
          user_sequence_no: 3,
          assistant_sequence_no: 4,
          turn_id: 'focus-turn',
        })
        handlers.onEvent('message_completed', {
          message_id: 'focus-assistant',
          status: 'completed',
        })
      },
    )
    const wrapper = mountView({ attachTo: document.body })
    await flushPromises()
    const textarea = wrapper.get('textarea').element

    textarea.blur()
    await wrapper.get('.thread-main').trigger('click')
    await flushPromises()
    expect(document.activeElement).toBe(textarea)

    textarea.blur()
    await wrapper.get('.new-thread').trigger('click')
    await flushPromises()
    expect(document.activeElement).toBe(textarea)

    await wrapper.get('textarea').setValue('完成后继续输入')
    textarea.blur()
    await wrapper.get('form.composer').trigger('submit')
    await flushPromises()
    expect(document.activeElement).toBe(textarea)

    wrapper.unmount()
  })

  it('把用户选中的消息、来源和产物作为显式引用发送', async () => {
    agentApi.streamAgentMessage.mockResolvedValue()
    const wrapper = mountView()
    await flushPromises()

    const referenceButtons = wrapper.findAll('button').filter(
      (item) => item.text() === '引用此消息',
    )
    await referenceButtons[0].trigger('click')
    const partToggles = wrapper.findAll('.parts-toggle')
    await partToggles[0].trigger('click')
    await partToggles[1].trigger('click')
    const partReferenceButtons = wrapper.findAll('button').filter(
      (item) => item.text() === '引用到下一轮',
    )
    await partReferenceButtons[0].trigger('click')
    await partReferenceButtons[1].trigger('click')
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
    state = reduceAgentEvent(state, 'decision', {
      action: 'finalize',
      summary: '现有结果足以完成任务，正在组织最终回答。',
    })
    state = reduceAgentEvent(state, 'token', { content: '完成' })

    expect(state.plan).toEqual(['检索资料'])
    expect(state.steps[0].tool_name).toBe('search_knowledge')
    expect(state.sources[0].page).toBe(3)
    expect(state.steps[0].decision_action).toBe('finalize')
    expect(state.output).toBe('完成')
    expect(state).not.toHaveProperty('chain_of_thought')
  })

  it('删除最后一个会话后同步清空右侧消息和运行详情', async () => {
    agentApi.deleteAgentThread.mockResolvedValue()
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('学习报告已完成')
    await wrapper.get('.thread-actions .danger').trigger('click')
    expect(wrapper.get('.thread-dialog').text()).toContain('删除会话')
    await wrapper.findAll('.thread-dialog footer button')[1].trigger('click')
    await flushPromises()

    expect(agentApi.deleteAgentThread).toHaveBeenCalledWith('thread-1')
    expect(wrapper.text()).not.toContain('学习报告已完成')
    expect(wrapper.text()).toContain('开始一段 Agent 对话')
    expect(wrapper.text()).toContain('新Agent会话')
  })

  it('时间线按sequence排序并对重复SSE实体做幂等更新', () => {
    let state = createAgentTimelineState()
    state = reduceAgentTimeline(state, 'optimistic_user', {
      id: 'pending-1',
      content: '你好',
    })
    state = reduceAgentTimeline(state, 'message_created', {
      user_message_id: 'user-1',
      assistant_message_id: 'assistant-1',
      user_sequence_no: 9,
      assistant_sequence_no: 10,
      turn_id: 'turn-1',
      run_id: 'run-1',
    })
    state = reduceAgentTimeline(state, 'tool_started', {
      step_id: 'step-1',
      step: 1,
      tool_name: 'search_knowledge',
    })
    state = reduceAgentTimeline(state, 'tool_started', {
      step_id: 'step-1',
      step: 1,
      tool_name: 'search_knowledge',
    })
    state = reduceAgentTimeline(state, 'token', { content: '完成' })
    expect(state.messages['assistant-1'].content).toBe('完成')
    expect(state.messages['assistant-1'].parts.steps).toHaveLength(1)
    expect(state.messages['user-1'].sequence_no).toBe(9)
  })
})
