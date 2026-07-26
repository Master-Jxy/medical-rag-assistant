export const initialAgentStreamState = () => ({
  phase: 'idle',
  runId: '',
  assistantMessageId: '',
  plan: [],
  steps: [],
  output: '',
  sources: [],
  artifacts: [],
  error: '',
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
    return { ...state, phase: data.status || 'completed' }
  }
  if (event === 'stopped') return { ...state, phase: 'stopped' }
  if (event === 'error') {
    return { ...state, phase: 'failed', error: data.message || 'Agent运行失败。' }
  }
  return state
}
