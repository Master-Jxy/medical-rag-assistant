import http from './http'

export async function getReviews(params = {}) {
  return (await http.get('/admin/reviews', { params })).data
}

export async function approveReview(id) {
  return (await http.post(`/admin/reviews/${id}/approve`)).data
}

export async function rejectReview(id, reason) {
  return (await http.post(`/admin/reviews/${id}/reject`, { reason })).data
}

export async function acceptMetadataSuggestion(id, payload) {
  return (await http.post(`/admin/reviews/${id}/metadata-suggestion/accept`, payload)).data
}

export async function rejectMetadataSuggestion(id, payload) {
  return (await http.post(`/admin/reviews/${id}/metadata-suggestion/reject`, payload)).data
}

export async function getAssets(params = {}) {
  return (await http.get('/admin/knowledge-assets', { params })).data
}

export async function updateAsset(id, payload) {
  return (await http.patch(`/admin/knowledge-assets/${id}`, payload)).data
}

export async function archiveAsset(id) {
  return (await http.post(`/admin/knowledge-assets/${id}/archive`)).data
}

export async function republishAsset(id) {
  return (await http.post(`/admin/knowledge-assets/${id}/republish`)).data
}

export async function scanKnowledgeGovernance() {
  return (await http.post('/admin/knowledge-assets/governance/scan')).data
}

export async function reviewKnowledgeAsset(id, payload) {
  return (await http.post(`/admin/knowledge-assets/${id}/review`, payload)).data
}

export async function getJobs(params = {}) {
  return (await http.get('/admin/jobs', { params })).data
}

export async function retryJob(id) {
  return (await http.post(`/admin/jobs/${id}/retry`)).data
}

export async function getAudit(params = {}) {
  return (await http.get('/admin/audit', { params })).data
}

export async function getUsers(params = {}) {
  return (await http.get('/super-admin/users', { params })).data
}

export async function updateUserRole(id, role) {
  return (await http.patch(`/super-admin/users/${id}/role`, { role })).data
}

export async function updateUserStatus(id, isActive) {
  return (await http.patch(`/super-admin/users/${id}/status`, { is_active: isActive })).data
}
