const TOKEN_KEY = 'medical-rag-access-token'

export const AUTH_UNAUTHORIZED_EVENT = 'medical-rag:unauthorized'

export function getAccessToken() {
  return window.localStorage.getItem(TOKEN_KEY) || ''
}

export function setAccessToken(token) {
  window.localStorage.setItem(TOKEN_KEY, token)
}

export function clearAccessToken() {
  window.localStorage.removeItem(TOKEN_KEY)
}

export function getAuthorizationHeaders() {
  const token = getAccessToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export function notifyUnauthorized() {
  const hadToken = Boolean(getAccessToken())
  clearAccessToken()
  if (hadToken) window.dispatchEvent(new CustomEvent(AUTH_UNAUTHORIZED_EVENT))
}
