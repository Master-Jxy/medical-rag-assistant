import { reactive } from 'vue'

import { getCurrentUser, loginUser, registerUser } from '../api/auth.js'
import {
  AUTH_UNAUTHORIZED_EVENT,
  clearAccessToken,
  getAccessToken,
  setAccessToken,
} from './token.js'
import { clearAgentTimelines } from '../features/agent-chat/useAgentTimeline.js'
import { clearAgentDrafts } from '../features/agent-chat/useAgentDraftRegistry.js'
import { abortAllConversationStreams } from '../features/agent-chat/useConversationStreamRegistry.js'

const state = reactive({
  user: null,
  ready: false,
})

let initialization = null

export function useAuthSession() {
  return state
}

function clearPrivateSessionState() {
  abortAllConversationStreams()
  clearAgentTimelines()
  clearAgentDrafts()
}

export async function initializeAuth() {
  if (state.ready) return state.user
  if (initialization) return initialization

  initialization = (async () => {
    const token = getAccessToken()
    if (!token) {
      state.user = null
      state.ready = true
      return null
    }

    try {
      state.user = await getCurrentUser()
      return state.user
    } catch {
      clearPrivateSessionState()
      clearAccessToken()
      state.user = null
      return null
    } finally {
      state.ready = true
      initialization = null
    }
  })()
  return initialization
}

export async function signIn(credentials) {
  clearPrivateSessionState()
  clearAccessToken()
  state.user = null
  state.ready = true
  const token = await loginUser(credentials)
  setAccessToken(token.access_token)
  try {
    state.user = await getCurrentUser()
    state.ready = true
    return state.user
  } catch (error) {
    clearAccessToken()
    state.user = null
    state.ready = true
    throw error
  }
}

export async function signUp(registration) {
  return registerUser(registration)
}

export function signOut() {
  clearPrivateSessionState()
  clearAccessToken()
  state.user = null
  state.ready = true
}

window.addEventListener(AUTH_UNAUTHORIZED_EVENT, () => {
  clearPrivateSessionState()
  state.user = null
  state.ready = true
})
