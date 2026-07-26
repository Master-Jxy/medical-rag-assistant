import http from './http'

export async function getProfile() {
  return (await http.get('/profile')).data
}

export async function getPersonalStats() {
  return (await http.get('/me/stats')).data
}

export async function getMySubmissions() {
  return (await http.get('/knowledge/submissions')).data
}

export async function withdrawSubmission(submissionId) {
  return (await http.post(`/knowledge/submissions/${submissionId}/withdraw`)).data
}

export async function getMemorySettings() {
  return (await http.get('/profile/memory-settings')).data
}

export async function updateMemorySettings(enabled) {
  return (await http.put('/profile/memory-settings', { enabled })).data
}

export async function getMemories() {
  return (await http.get('/profile/memories')).data
}

export async function createMemory(label, content) {
  return (await http.post('/profile/memories', { label, content })).data
}

export async function deleteMemory(id) {
  await http.delete(`/profile/memories/${id}`)
}
