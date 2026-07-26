import http from './http.js'

export async function submitAnswerFeedback(messageId, payload) {
  return (await http.put(`/quality/messages/${messageId}/feedback`, {
    ...payload,
  })).data
}

export async function getQualityOverview() {
  return (await http.get('/admin/quality/overview')).data
}

export async function getQualityReviews() {
  return (await http.get('/admin/quality/reviews', { params: { offset: 0, limit: 50 } })).data
}

export async function getQualityReview(id) {
  return (await http.get(`/admin/quality/reviews/${id}`)).data
}

export async function reviewQualityFeedback(id, status, note) {
  return (await http.patch(`/admin/quality/reviews/${id}`, { status, note })).data
}
