import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const platformApi = vi.hoisted(() => ({
  archiveAsset: vi.fn(),
  getAssets: vi.fn(),
  republishAsset: vi.fn(),
  reviewKnowledgeAsset: vi.fn(),
  scanKnowledgeGovernance: vi.fn(),
  updateAsset: vi.fn(),
}))
const documentApi = vi.hoisted(() => ({
  createSystemDocument: vi.fn(),
  deleteSystemDocument: vi.fn(),
  replaceSystemDocument: vi.fn(),
}))

vi.mock('../src/api/adminPlatform.js', () => platformApi)
vi.mock('../src/api/adminDocuments.js', () => documentApi)

import AdminAssetsView from '../src/views/AdminAssetsView.vue'

const systemAsset = {
  document_id: 'system-1',
  file_name: '系统资料.txt',
  is_system: true,
  status: 'published',
  source: 'system',
  tags: ['医学指南'],
  version: 1,
  chunk_count: 2,
  category: '诊疗规范',
  department: '心血管内科',
  review_status: 'current',
  is_expired: false,
}

beforeEach(() => {
  vi.clearAllMocks()
  platformApi.getAssets.mockResolvedValue({ items: [systemAsset], total: 1 })
  platformApi.updateAsset.mockResolvedValue(systemAsset)
  platformApi.scanKnowledgeGovernance.mockResolvedValue({ count: 0 })
  documentApi.createSystemDocument.mockResolvedValue({ file_name: '新增.txt' })
  documentApi.replaceSystemDocument.mockResolvedValue({ file_name: '新版.txt' })
  documentApi.deleteSystemDocument.mockResolvedValue({ document_id: 'system-1' })
})

describe('统一知识资产页面', () => {
  it('统一展示筛选、系统资料操作和选择式治理字段', async () => {
    const wrapper = mount(AdminAssetsView, {
      global: { stubs: { teleport: true } },
    })
    await flushPromises()

    expect(platformApi.getAssets).toHaveBeenCalledWith({ limit: 100 })
    expect(wrapper.text()).toContain('统一管理用户提交和系统资料')
    expect(wrapper.findAll('.asset-table > article')).toHaveLength(1)
    expect(wrapper.findAll('.asset-filters select')).toHaveLength(4)

    await wrapper.findAll('.asset-filters select')[0].setValue('system')
    await wrapper.get('.asset-filters').trigger('submit')
    await flushPromises()
    expect(platformApi.getAssets).toHaveBeenLastCalledWith({ limit: 100, source: 'system' })

    const editButton = wrapper.find('button[title="编辑治理信息"]')
    await editButton.trigger('click')
    expect(wrapper.find('.asset-form select').exists()).toBe(true)
    expect(wrapper.find('.tag-selector').text()).toContain('医学指南')

    const file = new File(['新增内容'], '新增.txt', { type: 'text/plain' })
    const input = wrapper.get('.file-picker input').element
    Object.defineProperty(input, 'files', { value: [file], configurable: true })
    await wrapper.get('.file-picker input').trigger('change')
    await wrapper.find('.upload-body .primary-action').trigger('click')
    await flushPromises()
    expect(documentApi.createSystemDocument).toHaveBeenCalledWith(file)
  })
})
