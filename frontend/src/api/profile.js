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
