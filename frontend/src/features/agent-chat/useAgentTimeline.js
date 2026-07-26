import { computed, ref } from 'vue'

export function createAgentTimelineState() {
  return {
    messages: {},
    pendingUserId: '',
    currentAssistantId: '',
  }
}

function normalizedMessage(message, run = null) {
  return {
    ...message,
    sequence_no: Number(message.sequence_no ?? Number.MAX_SAFE_INTEGER),
    parts: {
      plan: [],
      steps: run?.steps || [],
      sources: message.metadata?.sources || [],
      artifacts: run?.artifacts || [],
    },
  }
}

export function hydrateAgentTimeline(state, messages, runDetails = {}) {
  const entities = {}
  for (const message of messages) {
    entities[message.id] = normalizedMessage(
      message,
      runDetails[message.run_id] || runDetails[message.id],
    )
  }
  return { ...createAgentTimelineState(), messages: entities }
}

export function reduceAgentTimeline(state, event, data = {}) {
  const next = {
    ...state,
    messages: { ...state.messages },
  }
  if (event === 'optimistic_user') {
    const id = data.id
    next.pendingUserId = id
    next.messages[id] = normalizedMessage({
      id,
      role: 'user',
      content: data.content,
      status: 'pending',
      sequence_no: Number.MAX_SAFE_INTEGER - 1,
      metadata: {},
    })
    return next
  }
  if (event === 'message_created') {
    const pending = next.messages[next.pendingUserId]
    const storedUser = next.messages[data.user_message_id]
    if (next.pendingUserId) delete next.messages[next.pendingUserId]
    next.messages[data.user_message_id] = normalizedMessage({
      id: data.user_message_id,
      role: 'user',
      content: pending?.content || storedUser?.content || '',
      status: 'completed',
      sequence_no: data.user_sequence_no,
      turn_id: data.turn_id,
      metadata: {},
    })
    next.messages[data.assistant_message_id] = normalizedMessage({
      id: data.assistant_message_id,
      role: 'assistant',
      content: '',
      status: 'streaming',
      sequence_no: data.assistant_sequence_no,
      turn_id: data.turn_id,
      run_id: data.run_id,
      metadata: {},
    })
    next.pendingUserId = ''
    next.currentAssistantId = data.assistant_message_id
    return next
  }
  const message = next.messages[next.currentAssistantId]
  if (!message) return next
  const updated = {
    ...message,
    parts: {
      ...message.parts,
      plan: [...message.parts.plan],
      steps: [...message.parts.steps],
      sources: [...message.parts.sources],
      artifacts: [...message.parts.artifacts],
    },
  }
  if (event === 'plan_ready') updated.parts.plan = data.plan || []
  if (event === 'tool_started') {
    const stepId = data.step_id || `step-${data.step}`
    const index = updated.parts.steps.findIndex((item) => item.id === stepId)
    const step = {
      id: stepId,
      sequence: data.step,
      tool_name: data.tool_name,
      status: 'running',
      result_summary: '',
    }
    if (index >= 0) updated.parts.steps[index] = {
      ...updated.parts.steps[index],
      ...step,
    }
    else updated.parts.steps.push(step)
  }
  if (event === 'tool_completed') {
    const stepId = data.step_id
    const index = updated.parts.steps.findIndex((item) => (
      stepId ? item.id === stepId : item.tool_name === data.tool_name
    ))
    if (index >= 0) updated.parts.steps[index] = {
      ...updated.parts.steps[index],
      status: data.status,
      result_summary: data.summary || '',
    }
  }
  if (event === 'decision' && updated.parts.steps.length) {
    const lastIndex = updated.parts.steps.length - 1
    updated.parts.steps[lastIndex] = {
      ...updated.parts.steps[lastIndex],
      decision_action: data.action || '',
      decision_summary: data.summary || '',
    }
  }
  if (event === 'sources') {
    const incoming = data.items?.length
      ? data.items
      : (data.source_ids || []).map((document_id) => ({ document_id }))
    for (const source of incoming) {
      const key = `${source.document_id}:${source.chunk_id || ''}:${source.page || ''}`
      if (!updated.parts.sources.some((item) => (
        `${item.document_id}:${item.chunk_id || ''}:${item.page || ''}` === key
      ))) updated.parts.sources.push(source)
    }
  }
  if (event === 'artifact_ready') {
    if (!updated.parts.artifacts.some((item) => (
      item.id === data.artifact_id || item.artifact_id === data.artifact_id
    ))) updated.parts.artifacts.push({
      id: data.artifact_id,
      ...data,
    })
  }
  if (event === 'token') updated.content += data.content || ''
  if (event === 'message_completed') {
    updated.status = data.status || 'completed'
    updated.sequence_no = Number(data.sequence_no ?? updated.sequence_no)
  }
  if (event === 'stopped') updated.status = 'stopped'
  if (event === 'error') updated.status = 'failed'
  next.messages[updated.id] = updated
  return next
}

export function useAgentTimeline() {
  const state = ref(createAgentTimelineState())
  const messages = computed(() => Object.values(state.value.messages).sort(
    (left, right) => (
      left.sequence_no - right.sequence_no
      || String(left.id).localeCompare(String(right.id))
    ),
  ))
  function hydrate(rows, runDetails) {
    state.value = hydrateAgentTimeline(state.value, rows, runDetails)
  }
  function beginUser(content) {
    const id = `pending-${Date.now()}`
    state.value = reduceAgentTimeline(
      state.value,
      'optimistic_user',
      { id, content },
    )
  }
  function handle(event, data) {
    state.value = reduceAgentTimeline(state.value, event, data)
  }
  return { state, messages, hydrate, beginUser, handle }
}
