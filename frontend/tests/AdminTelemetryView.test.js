import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const telemetryApi = vi.hoisted(() => ({ getTelemetryStats: vi.fn() }))
vi.mock('../src/api/adminTelemetry.js', () => telemetryApi)

import AdminTelemetryView from '../src/views/AdminTelemetryView.vue'

beforeEach(() => {
  vi.clearAllMocks()
  telemetryApi.getTelemetryStats.mockResolvedValue({
    request_total: 10,
    request_success: 9,
    request_failure: 1,
    success_rate: 0.9,
    average_duration_ms: 12.5,
    stage_average_duration_ms: {
      query_construction: 1,
      knowledge_retrieval: 3,
      rerank: null,
      model_generation: 8,
      tool: null,
    },
    input_tokens: 0,
    output_tokens: 0,
    token_measurement: 'unknown',
    estimated_cost_cny: null,
    rate_limit_count: 1,
    redis_degradation_count: 2,
    user_stop_count: 3,
    failure_counts: { model: 1, retrieval: 0, persistence: 0 },
    error_type_counts: { TimeoutError: 1 },
  })
})

describe('管理员运行统计页面', () => {
  it('只展示聚合指标，并明确未知Token和费用', async () => {
    const wrapper = mount(AdminTelemetryView)
    await flushPromises()

    expect(telemetryApi.getTelemetryStats).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('请求总量')
    expect(wrapper.text()).toContain('90.0%')
    expect(wrapper.text()).toContain('未知（模型未返回计量）')
    expect(wrapper.text()).toContain('TimeoutError')
    expect(wrapper.text()).not.toContain('问题正文')
  })
})
