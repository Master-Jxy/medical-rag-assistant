import http from './http'

function formDataFor(file) {
  const formData = new FormData()
  formData.append('file', file)
  return formData
}

export async function createSystemDocument(file) {
  const response = await http.post('/admin/documents', formDataFor(file))
  return response.data
}

export async function replaceSystemDocument(documentId, file) {
  const response = await http.put(`/admin/documents/${documentId}/replace`, formDataFor(file))
  return response.data
}

export async function deleteSystemDocument(documentId) {
  const response = await http.delete(`/admin/documents/${documentId}`)
  return response.data
}
