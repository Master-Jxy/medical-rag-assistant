import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const platformApi = vi.hoisted(() => ({
  archiveAsset: vi.fn(),
  deferKnowledgeAssetReview: vi.fn(),
  expireKnowledgeAsset: vi.fn(),
  getAssets: vi.fn(),
  republishAsset: vi.fn(),
  restoreKnowledgeAsset: vi.fn(),
  reviewKnowledgeAsset: vi.fn(),
  scanKnowledgeGovernance: vi.fn(),
  updateAsset: vi.fn(),
}))
const documentApi = vi.hoisted(() => ({
  createSystemDocument: vi.fn(),
  deleteAdminDocument: vi.fn(),
  replaceAdminDocument: vi.fn(),
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
  governance_status: 'current',
  is_expired: false,
  supersedes_document_id: null,
  parser_version: 'knowledge_parser_v1',
  corpus_version: 'live_v1',
  duplicate_candidates: [{
    duplicate_type: 'near',
    candidate_document_id: 'user-1',
    candidate_file_name: '用户审核资料.txt',
    candidate_version: 1,
    score: 0.92,
    distance: 5,
    threshold: 8,
    reason: '近重复 SimHash 距离低于阈值',
  }],
}

const userAsset = {
  ...systemAsset,
  document_id: 'user-1',
  file_name: '用户审核资料.txt',
  is_system: false,
  source: 'user_submission',
}

beforeEach(() => {
  vi.clearAllMocks()
  platformApi.getAssets.mockResolvedValue({ items: [systemAsset, userAsset], total: 2 })
  platformApi.updateAsset.mockResolvedValue(systemAsset)
  platformApi.scanKnowledgeGovernance.mockResolvedValue({ count: 0 })
  platformApi.deferKnowledgeAssetReview.mockResolvedValue(systemAsset)
  platformApi.expireKnowledgeAsset.mockResolvedValue({ ...systemAsset, governance_status: 'expired', is_expired: true })
  platformApi.restoreKnowledgeAsset.mockResolvedValue(systemAsset)
  documentApi.createSystemDocument.mockResolvedValue({ file_name: '新增.txt' })
  documentApi.replaceAdminDocument.mockResolvedValue({ file_name: '新版.txt' })
  documentApi.deleteAdminDocument.mockResolvedValue({ document_id: 'system-1' })
})

describe('统一知识资产页面', () => {
  it('统一展示筛选、系统资料操作和选择式治理字段', async () => {
    const wrapper = mount(AdminAssetsView, {
      global: { stubs: { teleport: true } },
    })
    await flushPromises()

    expect(platformApi.getAssets).toHaveBeenCalledWith({ limit: 100 })
    expect(wrapper.text()).toContain('统一管理用户提交和系统资料')
    expect(wrapper.text()).toContain('近重复：用户审核资料.txt')
    expect(wrapper.findAll('.asset-table > article')).toHaveLength(2)
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

    expect(wrapper.get('.file-picker input').attributes('accept')).toContain('.docx')
    expect(wrapper.get('.file-picker input').attributes('accept')).toContain('.html')
    expect(wrapper.get('.file-picker input').attributes('accept')).toContain('.png')
  })

  it('系统资料和用户审核资料都提供整份替换与永久删除', async () => {
    const wrapper = mount(AdminAssetsView, {
      global: { stubs: { teleport: true } },
    })
    await flushPromises()

    expect(wrapper.findAll('.file-action')).toHaveLength(2)
    expect(wrapper.findAll('button[title="永久删除知识资产"]')).toHaveLength(2)

    const replacement = new File(['用户新版'], '用户新版.txt', { type: 'text/plain' })
    const userReplaceInput = wrapper.findAll('.file-action input')[1]
    Object.defineProperty(userReplaceInput.element, 'files', { value: [replacement], configurable: true })
    await userReplaceInput.trigger('change')
    await flushPromises()
    expect(documentApi.replaceAdminDocument).toHaveBeenCalledWith('user-1', replacement)
    expect(userReplaceInput.attributes('accept')).toContain('.md')
    expect(userReplaceInput.attributes('accept')).toContain('.jpeg')

    await wrapper.findAll('button[title="永久删除知识资产"]')[1].trigger('click')
    await wrapper.get('.confirm-dialog .dialog-button.danger').trigger('click')
    await flushPromises()
    expect(documentApi.deleteAdminDocument).toHaveBeenCalledWith('user-1')
  })

  it('supports expiry governance actions without leaving the asset page', async () => {
    const wrapper = mount(AdminAssetsView, {
      global: { stubs: { teleport: true } },
    })
    await flushPromises()

    await wrapper.find('button[title="标记失效"]').trigger('click')
    await wrapper.get('.confirm-dialog .dialog-button.danger').trigger('click')
    await flushPromises()
    expect(platformApi.expireKnowledgeAsset).toHaveBeenCalledWith('system-1', {
      reason: '管理员标记失效',
    })

    const dueAsset = { ...systemAsset, governance_status: 'due', review_status: 'current' }
    platformApi.getAssets.mockResolvedValueOnce({ items: [dueAsset], total: 1 })
    const dueWrapper = mount(AdminAssetsView, {
      global: { stubs: { teleport: true } },
    })
    await flushPromises()
    await dueWrapper.find('button[title="延后复核"]').trigger('click')
    await flushPromises()
    expect(platformApi.deferKnowledgeAssetReview).toHaveBeenCalledWith('system-1', expect.objectContaining({
      note: '管理员延后复核',
    }))
  })
})
