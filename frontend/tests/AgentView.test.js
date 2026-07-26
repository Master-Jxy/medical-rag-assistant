import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const agentApi = vi.hoisted(() => ({
  createAgentRun: vi.fn(),
  downloadAgentArtifact: vi.fn(),
  getAgentRun: vi.fn(),
  listAgentRuns: vi.fn(),
  stopAgentRun: vi.fn(),
  streamAgentRun: vi.fn(),
}))
vi.mock('../src/api/agent.js', () => agentApi)

import AgentView from '../src/views/AgentView.vue'

const completed = {
  id: 'run-1',
  task: '整理患者安全资料',
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
  agentApi.listAgentRuns.mockResolvedValue({ items: [completed] })
  agentApi.getAgentRun.mockResolvedValue(completed)
  agentApi.stopAgentRun.mockResolvedValue({ status: 'stopping', message: '正在安全停止' })
})

describe('资料整理Agent工作台', () => {
  it('展示历史、步骤、计量和下载产物', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('资料整理 Agent')
    expect(wrapper.text()).toContain('generate_learning_report')
    expect(wrapper.text()).toContain('学习报告已完成')
    expect(wrapper.text()).toContain('Token：25')
    expect(wrapper.get('button.artifact-link').text()).toBe('学习报告.md')
  })

  it('按独立Agent事件更新计划和工具状态', async () => {
    agentApi.listAgentRuns.mockResolvedValue({ items: [] })
    agentApi.createAgentRun.mockResolvedValue({
      ...completed,
      status: 'pending',
      steps: [],
      artifacts: [],
      final_result: null,
    })
    agentApi.streamAgentRun.mockImplementation(async (_id, handlers) => {
      handlers.onEvent('plan_ready', { plan: ['检索资料', '生成报告'] })
      handlers.onEvent('tool_started', { tool_name: 'search_knowledge', step: 1 })
      handlers.onEvent('tool_completed', {
        tool_name: 'search_knowledge',
        status: 'completed',
        summary: '检索到2个片段',
      })
      handlers.onEvent('token', { content: '整理完成。' })
    })
    agentApi.getAgentRun.mockResolvedValue({
      ...completed,
      steps: [{
        id: 'step-search',
        sequence: 1,
        tool_name: 'search_knowledge',
        status: 'completed',
        result_summary: '检索到2个片段',
      }],
    })

    const wrapper = mountView()
    await flushPromises()
    await wrapper.get('textarea').setValue('整理资料')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(agentApi.streamAgentRun).toHaveBeenCalledWith('run-1', expect.any(Object))
    expect(wrapper.text()).toContain('检索到2个片段')
    expect(wrapper.text()).toContain('学习报告已完成')
  })
})
