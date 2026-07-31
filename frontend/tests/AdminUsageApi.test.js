import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../src/api/http', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: { items: [] } }),
  },
}))

import http from '../src/api/http'
import { getAdminUsageRecords } from '../src/api/adminUsage'

describe('admin usage api', () => {
  beforeEach(() => http.get.mockClear())

  it('不发送会触发后端枚举校验的空筛选值', async () => {
    await getAdminUsageRecords({
      user_id: '',
      model_name: '',
      surface: '',
      status: '',
    })

    expect(http.get).toHaveBeenCalledWith(
      '/admin/usage/records/filter',
      { params: {} },
    )
  })
})
