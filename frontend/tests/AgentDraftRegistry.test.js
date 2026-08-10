import { beforeEach, describe, expect, it, vi } from 'vitest'

import { deleteMediaAsset, uploadMediaAsset } from '../src/api/media.js'
import {
  clearAgentDrafts,
  useAgentDraftRegistry,
} from '../src/features/agent-chat/useAgentDraftRegistry.js'

vi.mock('../src/api/media.js', () => ({
  uploadMediaAsset: vi.fn(),
  deleteMediaAsset: vi.fn(() => Promise.resolve()),
}))

function image(name = 'report.png') {
  return new File([new Uint8Array(8)], name, { type: 'image/png' })
}

describe('Agent 多会话图片草稿 registry', () => {
  beforeEach(() => {
    clearAgentDrafts()
    vi.clearAllMocks()
    let sequence = 0
    globalThis.URL.createObjectURL = vi.fn(() => `blob:preview-${++sequence}`)
    globalThis.URL.revokeObjectURL = vi.fn()
  })

  it('按 thread 隔离文本、引用与附件，A接受不会清理B', async () => {
    const registry = useAgentDraftRegistry()
    const draftA = registry.draftFor('thread-a')
    const draftB = registry.draftFor('thread-b')
    draftA.state.content = '分析A图片'
    draftA.state.references.messageIds = ['message-a']
    draftA.attachments.addFiles([image('a.png')])
    draftB.state.content = '保留B草稿'
    draftB.state.references.sourceIds = ['source-b']
    draftB.attachments.addFiles([image('b.png')])
    uploadMediaAsset.mockResolvedValueOnce({ id: 'asset-a' })

    const submission = await registry.prepareSubmission('thread-a')
    expect(submission.content).toBe('分析A图片')
    expect(submission.references.messageIds).toEqual(['message-a'])
    expect(submission.attachments).toHaveLength(1)
    expect(registry.acceptSubmission('thread-a', 'wrong-submission')).toBe(false)
    expect(registry.acceptSubmission('thread-a', submission.submissionId)).toBe(true)

    expect(registry.draftFor('thread-a').state.content).toBe('')
    expect(registry.draftFor('thread-a').attachments.items.value).toHaveLength(0)
    expect(registry.draftFor('thread-b').state.content).toBe('保留B草稿')
    expect(registry.draftFor('thread-b').state.references.sourceIds).toEqual(['source-b'])
    expect(registry.draftFor('thread-b').attachments.items.value).toHaveLength(1)
    expect(deleteMediaAsset).not.toHaveBeenCalled()
    expect(URL.revokeObjectURL).not.toHaveBeenCalledWith('blob:preview-1')
  })

  it('首次建会话移动同一submission并在接受后生成可编辑新草稿', async () => {
    const registry = useAgentDraftRegistry()
    const initial = registry.draftFor(registry.NEW_THREAD_KEY)
    initial.state.content = '纯图片任务'
    initial.attachments.addFiles([image()])
    uploadMediaAsset.mockResolvedValueOnce({ id: 'asset-new' })
    const submission = await registry.prepareSubmission(registry.NEW_THREAD_KEY)

    expect(registry.moveSubmission(
      registry.NEW_THREAD_KEY,
      'thread-created',
      submission.submissionId,
    )).toBe(true)
    expect(registry.acceptSubmission('thread-created', submission.submissionId)).toBe(true)
    const nextDraft = registry.draftFor('thread-created').state
    expect(nextDraft.submissionId).not.toBe(submission.submissionId)
    expect(nextDraft.phase).toBe('editing')
    nextDraft.content = '运行中准备下一条'
    expect(registry.draftFor('thread-created').state.content).toBe('运行中准备下一条')
  })

  it('接受前上传失败恢复editing并保留原草稿供重试', async () => {
    const registry = useAgentDraftRegistry()
    const draft = registry.draftFor('thread-a')
    draft.state.content = '失败后仍保留'
    draft.attachments.addFiles([image()])
    uploadMediaAsset.mockRejectedValueOnce(new Error('offline'))

    await expect(registry.prepareSubmission('thread-a')).rejects.toThrow('offline')
    expect(draft.state.phase).toBe('editing')
    expect(draft.state.content).toBe('失败后仍保留')
    expect(draft.attachments.items.value[0].status).toBe('failed')
  })
})
