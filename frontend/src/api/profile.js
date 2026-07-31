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

export async function updateMemorySettings(enabled, autoExtractEnabled = false) {
  return (await http.put('/profile/memory-settings', { enabled, auto_extract_enabled: autoExtractEnabled })).data
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

export async function approveMemory(id) {
  return (await http.post(`/profile/memories/${id}/approve`)).data
}

export async function rejectMemory(id) {
  return (await http.post(`/profile/memories/${id}/reject`)).data
}

export async function getQuota() {
  return (await http.get('/profile/quota')).data
}

export async function getUsageSummary(days = 30) {
  return (await http.get('/profile/usage/summary', { params: { days } })).data
}

export async function getUsageRecords(offset = 0, limit = 20) {
  return (await http.get('/profile/usage/records', { params: { offset, limit } })).data
}

export async function getUsageTrend(days = 30) {
  return (await http.get('/profile/usage/trend', { params: { days } })).data
}

export async function getUsageDistribution(days = 30) {
  return (await http.get('/profile/usage/distribution', { params: { days } })).data
}
