import http from './http'

export async function getDocuments() {
  const response = await http.get('/documents')
  return response.data
}

export async function uploadDocument(file, onProgress) {
  const formData = new FormData()
  formData.append('file', file)

  const response = await http.post('/documents', formData, {
    onUploadProgress(event) {
      if (!event.total) return
      onProgress?.(Math.round((event.loaded * 100) / event.total))
    },
  })
  return response.data
}

export async function deleteDocument(documentId) {
  const response = await http.delete(`/documents/${documentId}`)
  return response.data
}
