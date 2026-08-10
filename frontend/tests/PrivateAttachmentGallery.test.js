import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getMediaPreview } from '../src/api/media.js'
import PrivateAttachmentGallery from '../src/features/attachments/PrivateAttachmentGallery.vue'
import {
  createAgentTimelineState,
  hydrateAgentTimeline,
  reduceAgentTimeline,
} from '../src/features/agent-chat/useAgentTimeline.js'

vi.mock('../src/api/media.js', () => ({ getMediaPreview: vi.fn() }))

function deferred() {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

describe('私有历史图片预览', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    globalThis.URL.createObjectURL = vi.fn((blob) => `blob:${blob.name}`)
    globalThis.URL.revokeObjectURL = vi.fn()
  })

  it('旧会话异步预览完成后不会覆盖新会话图片', async () => {
    const oldPreview = deferred()
    const newPreview = deferred()
    getMediaPreview.mockImplementation((id) => (
      id === 'old' ? oldPreview.promise : newPreview.promise
    ))
    const wrapper = mount(PrivateAttachmentGallery, {
      props: { attachments: [{ id: 'old', original_name: 'old.png' }] },
    })
    await wrapper.setProps({ attachments: [{ id: 'new', original_name: 'new.png' }] })
    newPreview.resolve({ name: 'new' })
    await flushPromises()
    expect(wrapper.get('img').attributes('src')).toBe('blob:new')

    oldPreview.resolve({ name: 'old' })
    await flushPromises()
    expect(wrapper.get('img').attributes('src')).toBe('blob:new')
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:old')
  })

  it('A到B再回A时本地URL保持有效，最终只由timeline释放', async () => {
    let timeline = createAgentTimelineState()
    timeline = reduceAgentTimeline(timeline, 'optimistic_user', {
      id: 'pending-a',
      submissionId: 'submission-a',
      content: 'A图片',
    })
    timeline = reduceAgentTimeline(timeline, 'message_created', {
      user_message_id: 'user-a',
      assistant_message_id: 'assistant-a',
      user_sequence_no: 1,
      assistant_sequence_no: 2,
      run_id: 'run-a',
      optimistic_attachments: [{ id: 'asset-a', localUrl: 'blob:a', original_name: 'a.png' }],
    })
    const wrapper = mount(PrivateAttachmentGallery, {
      props: { attachments: timeline.messages['user-a'].attachments },
    })
    await flushPromises()
    await wrapper.setProps({
      attachments: [{ id: 'asset-b', localUrl: 'blob:b', original_name: 'b.png' }],
    })
    await flushPromises()
    await wrapper.setProps({ attachments: timeline.messages['user-a'].attachments })
    await flushPromises()
    expect(wrapper.get('img').attributes('src')).toBe('blob:a')
    expect(URL.revokeObjectURL).not.toHaveBeenCalled()
    wrapper.unmount()
    expect(URL.revokeObjectURL).not.toHaveBeenCalled()

    hydrateAgentTimeline(timeline, [], {})
    expect(URL.revokeObjectURL).toHaveBeenCalledOnce()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:a')
  })
})
