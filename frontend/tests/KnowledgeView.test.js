import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  deleteDocument: vi.fn(),
  getDocuments: vi.fn(),
  uploadDocument: vi.fn(),
}))

vi.mock('../src/api/documents.js', () => api)

import KnowledgeView from '../src/views/KnowledgeView.vue'

const systemDocument = {
  document_id: 'system-1',
  file_name: '系统资料.txt',
  file_size: 100,
  chunk_count: 1,
  status: 'ready',
  is_system: true,
  can_delete: false,
  created_at: '2026-07-15T00:00:00Z',
}
const ownedDocument = {
  document_id: 'owned-1',
  file_name: '我的资料.txt',
  file_size: 200,
  chunk_count: 2,
  status: 'ready',
  is_system: false,
  can_delete: true,
  created_at: '2026-07-15T00:00:00Z',
}

function mountKnowledge() {
  return mount(KnowledgeView, {
    global: {
      stubs: {
        ElButton: { template: '<button v-bind="$attrs" @click="$emit(\'click\')"><slot /></button>' },
      },
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  api.getDocuments.mockResolvedValue({ documents: [systemDocument, ownedDocument] })
  api.deleteDocument.mockResolvedValue({ message: '文档已删除' })
})

describe('KnowledgeView 文档权限', () => {
  it('已发布公共文档统一显示为受保护资产，不提供永久删除入口', async () => {
    const wrapper = mountKnowledge()
    await flushPromises()

    expect(wrapper.text()).toContain('系统资料')
    expect(wrapper.findAll('.delete-button')).toHaveLength(0)
    expect(wrapper.text()).toContain('发布后由管理员统一治理')
  })

  it('上传成功只提示已提交审核，不提示已经入库', async () => {
    api.uploadDocument.mockResolvedValue({
      submission_id: 'submission-1',
      file_name: '待审核资料.txt',
      status: 'pending_review',
    })
    const wrapper = mountKnowledge()
    await flushPromises()

    const input = wrapper.get('input[type="file"]')
    const file = new File(['资料'], '待审核资料.txt', { type: 'text/plain' })
    Object.defineProperty(input.element, 'files', { value: [file] })
    await input.trigger('change')
    await wrapper.get('.upload-button').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('已提交，等待管理员审核')
    expect(wrapper.text()).not.toContain('已成功入库')
  })
})
