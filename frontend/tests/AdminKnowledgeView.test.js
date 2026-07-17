import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const documentsApi = vi.hoisted(() => ({ getDocuments: vi.fn() }))
const adminApi = vi.hoisted(() => ({
  createSystemDocument: vi.fn(),
  deleteSystemDocument: vi.fn(),
  replaceSystemDocument: vi.fn(),
}))

vi.mock('../src/api/documents.js', () => documentsApi)
vi.mock('../src/api/adminDocuments.js', () => adminApi)

import AdminKnowledgeView from '../src/views/AdminKnowledgeView.vue'

const systemDocument = {
  document_id: 'system-1',
  file_name: '系统资料.txt',
  file_size: 100,
  chunk_count: 2,
  is_system: true,
}

beforeEach(() => {
  vi.clearAllMocks()
  documentsApi.getDocuments.mockResolvedValue({
    documents: [systemDocument, { ...systemDocument, document_id: 'user-1', is_system: false }],
  })
  adminApi.createSystemDocument.mockResolvedValue({ file_name: '新增.txt' })
  adminApi.replaceSystemDocument.mockResolvedValue({ file_name: '新版.txt' })
  adminApi.deleteSystemDocument.mockResolvedValue({ document_id: 'system-1' })
})

describe('管理员知识库页面', () => {
  it('只展示系统资料，并可新增、整体替换和删除', async () => {
    const originalConfirm = window.confirm
    window.confirm = vi.fn(() => true)
    const wrapper = mount(AdminKnowledgeView)
    await flushPromises()

    expect(wrapper.findAll('.document-row')).toHaveLength(1)
    expect(wrapper.text()).toContain('系统资料.txt')

    const createFile = new File(['新增内容'], '新增.txt', { type: 'text/plain' })
    const createInput = wrapper.get('.file-picker input').element
    Object.defineProperty(createInput, 'files', { value: [createFile], configurable: true })
    await wrapper.get('.file-picker input').trigger('change')
    await wrapper.get('.create-card > button').trigger('click')
    await flushPromises()
    expect(adminApi.createSystemDocument).toHaveBeenCalledWith(createFile)

    const replaceFile = new File(['新版内容'], '新版.txt', { type: 'text/plain' })
    const replaceInput = wrapper.get('.replace-input').element
    Object.defineProperty(replaceInput, 'files', { value: [replaceFile], configurable: true })
    await wrapper.get('.replace-input').trigger('change')
    await flushPromises()
    expect(adminApi.replaceSystemDocument).toHaveBeenCalledWith('system-1', replaceFile)

    await wrapper.get('.delete-button').trigger('click')
    await flushPromises()
    expect(adminApi.deleteSystemDocument).toHaveBeenCalledWith('system-1')
    window.confirm = originalConfirm
  })
})
