export const initialAgentStreamState = () => ({
  phase: 'idle',
  runId: '',
  assistantMessageId: '',
  plan: [],
  steps: [],
  decisions: [],
  output: '',
  sources: [],
  artifacts: [],
  error: '',
  usage: null,
  quota: null,
})

export function reduceAgentEvent(state, event, data = {}) {
  if (event === 'message_created') {
    return {
      ...state,
      phase: 'planning',
      runId: data.run_id || '',
      assistantMessageId: data.assistant_message_id || '',
    }
  }
  if (event === 'run_started') return { ...state, phase: 'planning' }
  if (event === 'plan_ready') {
    return { ...state, phase: 'running_tools', plan: data.plan || [] }
  }
  if (event === 'tool_started') {
    return {
      ...state,
      phase: 'running_tools',
      steps: [...state.steps, {
        id: `live-${data.step}`,
        sequence: data.step,
        tool_name: data.tool_name,
        status: 'running',
        result_summary: '',
      }],
    }
  }
  if (event === 'tool_completed') {
    const steps = [...state.steps]
    const index = steps.findLastIndex((item) => item.tool_name === data.tool_name)
    if (index >= 0) steps[index] = {
      ...steps[index],
      status: data.status,
      result_summary: data.summary || '',
    }
    return { ...state, steps }
  }
  if (event === 'decision') {
    const decisions = [...state.decisions, {
      action: data.action || '',
      summary: data.summary || '',
    }]
    const steps = [...state.steps]
    if (steps.length) {
      steps[steps.length - 1] = {
        ...steps[steps.length - 1],
        decision_action: data.action || '',
        decision_summary: data.summary || '',
      }
    }
    return { ...state, decisions, steps }
  }
  if (event === 'sources') {
    return { ...state, sources: data.items?.length
      ? data.items
      : (data.source_ids || []).map((document_id) => ({ document_id })) }
  }
  if (event === 'artifact_ready') {
    return { ...state, artifacts: [...state.artifacts, data] }
  }
  if (event === 'token') {
    return {
      ...state,
      phase: 'streaming_answer',
      output: `${state.output}${data.content || ''}`,
    }
  }
  if (event === 'message_completed') {
    return { ...state, phase: data.status || 'completed', usage: data.usage || state.usage, quota: data.quota || state.quota }
  }
  if (event === 'run_completed') return { ...state, usage: data.usage || null, quota: data.quota || null }
  if (event === 'stopped') return { ...state, phase: 'stopped', usage: data.usage || state.usage, quota: data.quota || state.quota }
  if (event === 'error') {
    return { ...state, phase: 'failed', error: data.message || 'Agent运行失败。' }
  }
  return state
}
