import http from './http.js'

export async function registerUser(payload) {
  const response = await http.post('/auth/register', payload)
  return response.data
}

export async function requestEmailVerification(payload) {
  const response = await http.post('/auth/email-verification/request', payload)
  return response.data
}

export async function requestPasswordReset(payload) {
  const response = await http.post('/auth/password-reset/request', payload)
  return response.data
}

export async function confirmPasswordReset(payload) {
  const response = await http.post('/auth/password-reset/confirm', payload)
  return response.data
}

export async function loginUser(payload) {
  const response = await http.post('/auth/login', payload)
  return response.data
}

export async function getCurrentUser() {
  const response = await http.get('/auth/me')
  return response.data
}
