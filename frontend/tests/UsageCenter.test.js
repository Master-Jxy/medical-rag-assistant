import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../src/api/profile', () => ({
  getQuota: vi.fn(),
  getUsageSummary: vi.fn(),
  getUsageRecords: vi.fn(),
  getUsageTrend: vi.fn(),
  getUsageDistribution: vi.fn(),
}))

import {
  getQuota,
  getUsageDistribution,
  getUsageRecords,
  getUsageSummary,
  getUsageTrend,
} from '../src/api/profile'
import UsageCenter from '../src/features/profile/UsageCenter.vue'

describe('UsageCenter', () => {
  beforeEach(() => {
    getQuota.mockResolvedValue({
      token_limit: 1_000_000,
      used_tokens: 950_000,
      reserved_tokens: 0,
      remaining_tokens: 50_000,
      request_limit: 500,
      used_requests: 20,
      remaining_requests: 480,
      warning_level: 'critical',
      estimated_remaining_requests: 12,
      period_end: '2026-08-01T00:00:00Z',
    })
    getUsageSummary.mockResolvedValue({
      requests: 1,
      input_tokens: 120,
      output_tokens: 30,
    })
    getUsageRecords.mockResolvedValue({
      items: [{
        id: 'usage-1',
        created_at: '2026-07-31T00:00:00Z',
        surface: 'rag',
        model_name: 'fake',
        measurement: 'unknown',
        total_tokens: null,
        charged_tokens: 5711,
        estimated_cost_cny: null,
        latency_ms: 10,
      }],
    })
    getUsageTrend.mockResolvedValue({ items: [] })
    getUsageDistribution.mockResolvedValue({
      by_surface: [],
      by_model: [],
    })
  })

  it('展示100万额度、95%预警、请求余额和实际/扣减双口径', async () => {
    const wrapper = mount(UsageCenter)
    await flushPromises()

    expect(wrapper.text()).toContain('1,000,000 Token')
    expect(wrapper.text()).toContain('已使用至少 95%')
    expect(wrapper.text()).toContain('20 / 500')
    expect(wrapper.text()).toContain('约 12 次')
    expect(wrapper.text()).toContain('实际未知 · 扣减 5,711')
  })
})
