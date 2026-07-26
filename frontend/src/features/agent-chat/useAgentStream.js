import { computed, ref } from 'vue'
import {
  retryAgentMessage,
  stopAgentRun,
  streamAgentMessage,
} from '../../api/agent.js'
import {
  initialAgentStreamState,
  reduceAgentEvent,
} from './agentEventReducer.js'

function requestId() {
  return globalThis.crypto?.randomUUID?.()
    || `agent-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function useAgentStream(onSettled) {
  const state = ref(initialAgentStreamState())
  const running = computed(() => [
    'creating_message',
    'planning',
    'running_tools',
    'streaming_answer',
  ].includes(state.value.phase))

  function handle(event, data) {
    state.value = reduceAgentEvent(state.value, event, data)
  }

  async function send(threadId, content, references = {}) {
    state.value = { ...initialAgentStreamState(), phase: 'creating_message' }
    try {
      await streamAgentMessage(
        threadId,
        {
          content,
          referenced_message_ids: references.messageIds || [],
          source_ids: references.sourceIds || [],
          artifact_ids: references.artifactIds || [],
        },
        requestId(),
        { onEvent: handle },
      )
    } finally {
      await onSettled?.()
    }
  }

  async function retry(messageId) {
    state.value = { ...initialAgentStreamState(), phase: 'creating_message' }
    try {
      await retryAgentMessage(messageId, requestId(), { onEvent: handle })
    } finally {
      await onSettled?.()
    }
  }

  async function stop() {
    if (state.value.runId) await stopAgentRun(state.value.runId)
  }

  return { state, running, send, retry, stop }
}
