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
  it('系统文档显示保护状态，只有可删除文档出现删除按钮', async () => {
    const wrapper = mountKnowledge()
    await flushPromises()

    expect(wrapper.text()).toContain('系统资料')
    expect(wrapper.findAll('.delete-button')).toHaveLength(1)
    expect(wrapper.get('.delete-button').element.closest('.document-row').textContent).toContain('我的资料.txt')

    await wrapper.get('.delete-button').trigger('click')
    expect(wrapper.text()).toContain('确认删除文档？')
    expect(wrapper.text()).toContain('我的资料.txt')
  })
})
