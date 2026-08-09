import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAttachmentDraft } from '../src/features/attachments/useAttachmentDraft.js'
import { deleteMediaAsset, uploadMediaAsset } from '../src/api/media.js'

vi.mock('../src/api/media.js', () => ({
  uploadMediaAsset: vi.fn(),
  deleteMediaAsset: vi.fn(() => Promise.resolve()),
}))

const Harness = defineComponent({
  setup(_, { expose }) {
    const draft = useAttachmentDraft()
    expose(draft)
    return () => null
  },
})

function image(name = 'report.png', type = 'image/png', size = 8) {
  return new File([new Uint8Array(size)], name, { type })
}

describe('共享图片附件草稿', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:preview')
    globalThis.URL.revokeObjectURL = vi.fn()
  })

  it('限制类型、大小和三张上限', () => {
    const wrapper = mount(Harness)
    wrapper.vm.addFiles([image('a.png'), image('b.webp', 'image/webp'), image('c.jpg', 'image/jpeg')])
    expect(wrapper.vm.items).toHaveLength(3)
    wrapper.vm.addFiles([image('d.png')])
    expect(wrapper.vm.error).toContain('最多添加 3 张')
    wrapper.vm.completeSend()
    wrapper.vm.addFiles([image('bad.gif', 'image/gif')])
    expect(wrapper.vm.items).toHaveLength(0)
    expect(wrapper.vm.error).toContain('JPG、PNG、WEBP')
    wrapper.vm.unmount?.()
  })

  it('图片粘贴会接管事件，普通文字粘贴保持默认行为', () => {
    const wrapper = mount(Harness)
    const textPrevent = vi.fn()
    wrapper.vm.handlePaste({ clipboardData: { items: [{ kind: 'string', type: 'text/plain' }] }, preventDefault: textPrevent })
    expect(textPrevent).not.toHaveBeenCalled()
    const imagePrevent = vi.fn()
    const file = image()
    wrapper.vm.handlePaste({ clipboardData: { items: [{ kind: 'file', type: 'image/png', getAsFile: () => file }] }, preventDefault: imagePrevent })
    expect(imagePrevent).toHaveBeenCalledOnce()
    expect(wrapper.vm.items).toHaveLength(1)
  })

  it('上传失败保留草稿并可重试，删除已上传草稿调用私有删除接口', async () => {
    const wrapper = mount(Harness)
    wrapper.vm.addFiles([image()])
    uploadMediaAsset.mockRejectedValueOnce(new Error('offline'))
    await expect(wrapper.vm.uploadAll()).rejects.toThrow('offline')
    expect(wrapper.vm.items[0].status).toBe('failed')
    uploadMediaAsset.mockResolvedValueOnce({ id: 'asset-1' })
    await expect(wrapper.vm.upload(wrapper.vm.items[0])).resolves.toBe('asset-1')
    expect(wrapper.vm.items[0].status).toBe('uploaded')
    await wrapper.vm.remove(wrapper.vm.items[0])
    expect(deleteMediaAsset).toHaveBeenCalledWith('asset-1')
    expect(wrapper.vm.items).toHaveLength(0)
  })
})
