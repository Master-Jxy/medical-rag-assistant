import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const authState = vi.hoisted(() => ({ user: { role: 'admin' } }))
const usageApi = vi.hoisted(() => ({
  adjustUserQuota: vi.fn(),
  getAdminUsageOverview: vi.fn(),
  getAdminUsageRecords: vi.fn(),
  getAdminUsageTrend: vi.fn(),
  getAdminUsageUsers: vi.fn(),
}))

vi.mock('../src/auth/session', () => ({
  useAuthSession: () => authState,
}))
vi.mock('../src/api/adminUsage', () => usageApi)

import AdminUsageView from '../src/views/AdminUsageView.vue'

const userRow = {
  user_id: 'user-1',
  email: 'user@example.com',
  requests: 2,
  total_tokens: 300,
  unknown_calls: 0,
  failed_calls: 0,
  token_limit: 1_000_000,
  remaining_tokens: 999_700,
  quota_exhausted: false,
  warning_level: 'critical',
  token_limit_override: null,
  request_limit_override: null,
  estimated_cost_limit_cny_override: null,
}

beforeEach(() => {
  vi.clearAllMocks()
  usageApi.getAdminUsageOverview.mockResolvedValue({
    requests: 2,
    total_tokens: 300,
    estimated_cost_cny: 0,
    measurement_coverage: 1,
    unknown_calls: 0,
    failed_calls: 0,
    warning_users: 0,
    would_block_events: 0,
    reservation_underestimated_events: 0,
  })
  usageApi.getAdminUsageTrend.mockResolvedValue({ items: [] })
  usageApi.getAdminUsageUsers.mockResolvedValue({ items: [userRow] })
  usageApi.getAdminUsageRecords.mockResolvedValue({ items: [] })
  usageApi.adjustUserQuota.mockResolvedValue({})
})

describe('AdminUsageView额度权限', () => {
  it('普通管理员只读且看不到调整入口', async () => {
    authState.user = { role: 'admin' }
    const wrapper = mount(AdminUsageView)
    await flushPromises()

    expect(wrapper.text()).not.toContain('调整额度')
    expect(wrapper.text()).toContain('95% 预警')
    expect(wrapper.find('.quota-dialog').exists()).toBe(false)
  })

  it('超级管理员表单没有计划概念并提交三种数字覆盖值', async () => {
    authState.user = { role: 'super_admin' }
    const wrapper = mount(AdminUsageView)
    await flushPromises()
    await wrapper.get('button').trigger('click')

    const dialog = wrapper.get('.quota-dialog')
    expect(dialog.text()).not.toContain('计划')
    expect(dialog.text()).not.toContain('套餐')
    const inputs = dialog.findAll('input')
    await inputs[0].setValue('1500000')
    await inputs[1].setValue('800')
    await inputs[2].setValue('20.5')
    await dialog.get('textarea').setValue('阶段19本地测试')
    await dialog.trigger('submit')
    await flushPromises()

    expect(usageApi.adjustUserQuota).toHaveBeenCalledWith('user-1', {
      token_limit_override: 1500000,
      request_limit_override: 800,
      estimated_cost_limit_cny_override: 20.5,
      reason: '阶段19本地测试',
    })
  })
})
