import http, { apiBaseUrl, createApiErrorFromResponse } from './http.js'
import { getAuthorizationHeaders, notifyUnauthorized } from '../auth/token.js'

export async function getDocumentTrace(documentId) {
  return (await http.get(`/knowledge/documents/${documentId}/trace`)).data
}

export async function openDocumentPreview(documentId, page) {
  const response = await fetch(`${apiBaseUrl}/knowledge/documents/${encodeURIComponent(documentId)}/preview`, {
    headers: { ...getAuthorizationHeaders() },
  })
  if (!response.ok) {
    if (response.status === 401) notifyUnauthorized()
    throw await createApiErrorFromResponse(response)
  }
  const url = URL.createObjectURL(await response.blob())
  window.open(`${url}${page ? `#page=${page}` : ''}`, '_blank', 'noopener')
  window.setTimeout(() => URL.revokeObjectURL(url), 60000)
}
