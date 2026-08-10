import { markRaw, reactive } from 'vue'

import {
  createAttachmentDraftController,
  createAttachmentDraftState,
} from '../attachments/useAttachmentDraft.js'

const NEW_THREAD_KEY = '__new_agent_thread__'
const states = reactive(new Map())
const controllers = new Map()

function identifier(prefix = 'submission') {
  return globalThis.crypto?.randomUUID?.()
    || `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function emptyReferences() {
  return { messageIds: [], sourceIds: [], artifactIds: [] }
}

function createState(threadKey) {
  return reactive({
    threadKey,
    submissionId: identifier(),
    phase: 'editing',
    content: '',
    references: emptyReferences(),
    attachmentState: createAttachmentDraftState(),
  })
}

function ensureState(threadKey) {
  const key = threadKey || NEW_THREAD_KEY
  if (!states.has(key)) states.set(key, createState(key))
  return states.get(key)
}

function controllerFor(threadKey) {
  const key = threadKey || NEW_THREAD_KEY
  if (!controllers.has(key)) {
    controllers.set(key, markRaw(
      createAttachmentDraftController(ensureState(key).attachmentState),
    ))
  }
  return controllers.get(key)
}

function replaceWithEmpty(threadKey) {
  controllers.delete(threadKey)
  states.set(threadKey, createState(threadKey))
}

export function useAgentDraftRegistry() {
  function draftFor(threadKey) {
    const key = threadKey || NEW_THREAD_KEY
    return { state: ensureState(key), attachments: controllerFor(key) }
  }

  async function prepareSubmission(threadKey) {
    const key = threadKey || NEW_THREAD_KEY
    const draft = draftFor(key)
    if (draft.state.phase !== 'editing') {
      throw new Error('当前草稿正在提交，请稍候。')
    }
    draft.state.phase = 'uploading'
    try {
      const attachmentIds = await draft.attachments.uploadAll()
      draft.state.phase = 'awaiting_acceptance'
      return Object.freeze({
        threadKey: key,
        submissionId: draft.state.submissionId,
        content: draft.state.content.trim(),
        references: Object.freeze({
          messageIds: Object.freeze([...draft.state.references.messageIds]),
          sourceIds: Object.freeze([...draft.state.references.sourceIds]),
          artifactIds: Object.freeze([...draft.state.references.artifactIds]),
        }),
        attachmentIds: Object.freeze([...attachmentIds]),
        attachments: Object.freeze(draft.attachments.snapshot().map(Object.freeze)),
      })
    } catch (error) {
      draft.state.phase = 'editing'
      throw error
    }
  }

  function moveSubmission(fromThreadKey, toThreadKey, submissionId) {
    if (fromThreadKey === toThreadKey) return true
    const state = states.get(fromThreadKey)
    if (!state || state.submissionId !== submissionId) return false
    const replaced = states.get(toThreadKey)
    if (replaced) controllerFor(toThreadKey).dispose()
    states.delete(fromThreadKey)
    controllers.delete(toThreadKey)
    const controller = controllers.get(fromThreadKey)
    controllers.delete(fromThreadKey)
    state.threadKey = toThreadKey
    states.set(toThreadKey, state)
    if (controller) controllers.set(toThreadKey, controller)
    return true
  }

  function acceptSubmission(threadKey, submissionId) {
    const state = states.get(threadKey)
    if (!state || state.submissionId !== submissionId) return false
    controllerFor(threadKey).completeSend({ preserveLocalUrls: true })
    replaceWithEmpty(threadKey)
    return true
  }

  function failSubmission(threadKey, submissionId) {
    const state = states.get(threadKey)
    if (!state || state.submissionId !== submissionId) return false
    if (state.phase === 'awaiting_acceptance') state.phase = 'editing'
    return true
  }

  function remove(threadKey) {
    const state = states.get(threadKey)
    if (!state) return
    controllerFor(threadKey).dispose()
    states.delete(threadKey)
    controllers.delete(threadKey)
  }

  return {
    NEW_THREAD_KEY,
    states,
    draftFor,
    prepareSubmission,
    moveSubmission,
    acceptSubmission,
    failSubmission,
    remove,
  }
}

export function clearAgentDrafts() {
  for (const key of states.keys()) controllerFor(key).dispose()
  states.clear()
  controllers.clear()
}
