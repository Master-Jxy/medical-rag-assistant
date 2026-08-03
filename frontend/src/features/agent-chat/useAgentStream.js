import {
  retryAgentMessage,
  stopAgentRun,
  streamAgentMessage,
} from '../../api/agent.js'
import {
  initialAgentStreamState,
  reduceAgentEvent,
} from './agentEventReducer.js'
import { useConversationStreamRegistry } from './useConversationStreamRegistry.js'

function requestId() {
  return globalThis.crypto?.randomUUID?.()
    || `agent-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function useAgentStream(onSettled, onEvent) {
  const registry = useConversationStreamRegistry('agent')

  function stateFor(threadId) {
    return registry.get(threadId)?.state || initialAgentStreamState()
  }

  function runningFor(threadId, serverStatus = 'idle') {
    return registry.isRunning(threadId, serverStatus)
  }

  function handle(threadId, event, data) {
    if (!registry.acceptEvent(threadId, data)) return
    const entry = registry.get(threadId)
    if (!entry) return
    entry.state = reduceAgentEvent(entry.state, event, data)
    entry.phase = ['completed', 'failed', 'stopped'].includes(entry.state.phase)
      ? 'settling'
      : entry.state.phase
    entry.runId = entry.state.runId || entry.runId
    onEvent?.(threadId, event, data)
  }

  async function runStream(threadId, operation) {
    const entry = registry.start(threadId, {
      phase: 'creating_message',
      state: { ...initialAgentStreamState(), phase: 'creating_message' },
    })
    try {
      await operation(entry, (event, data) => handle(threadId, event, data))
      if (entry.phase === 'settling') {
        entry.phase = entry.state.phase
      } else if (registry.isRunning(threadId)) {
        entry.state = { ...entry.state, phase: 'completed' }
        entry.phase = 'completed'
      }
    } catch (error) {
      if (error?.name === 'AbortError') {
        entry.state = { ...entry.state, phase: 'stopped' }
        entry.phase = 'stopped'
      } else {
        entry.state = {
          ...entry.state,
          phase: 'failed',
          error: error?.userMessage || error?.message || 'Agent运行失败。',
        }
        entry.phase = 'failed'
        entry.error = entry.state.error
      }
      throw error
    } finally {
      entry.controller = null
      await onSettled?.(threadId, entry.state)
    }
  }

  function send(threadId, content, references = {}) {
    return runStream(threadId, (entry, handleEvent) => streamAgentMessage(
      threadId,
      {
        content,
        referenced_message_ids: references.messageIds || [],
        source_ids: references.sourceIds || [],
        artifact_ids: references.artifactIds || [],
      },
      requestId(),
      { onEvent: handleEvent, signal: entry.controller.signal },
    ))
  }

  function retry(threadId, messageId) {
    return runStream(threadId, (entry, handleEvent) => retryAgentMessage(
      messageId,
      requestId(),
      { onEvent: handleEvent, signal: entry.controller.signal },
    ))
  }

  async function stop(threadId, fallbackRunId = '') {
    const entry = registry.get(threadId)
    if (entry?.phase === 'stopping') return
    const runId = entry?.runId || fallbackRunId
    if (!runId) return
    registry.patch(threadId, { phase: 'stopping' })
    if (entry) entry.state = { ...entry.state, phase: 'stopping' }
    const result = await stopAgentRun(runId)
    if (result.status !== 'stopping') registry.abort(threadId)
    return result
  }

  function abortAll() {
    registry.abortAll()
  }

  return {
    registry,
    stateFor,
    runningFor,
    send,
    retry,
    stop,
    abortAll,
  }
}
