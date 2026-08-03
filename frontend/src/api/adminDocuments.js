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

export async function replaceAdminDocument(documentId, file) {
  const response = await http.put(`/admin/documents/${documentId}/replace`, formDataFor(file))
  return response.data
}

export async function deleteAdminDocument(documentId) {
  const response = await http.delete(`/admin/documents/${documentId}`)
  return response.data
}

// 兼容旧调用名；后端入口已统一支持系统资料和用户审核发布资料。
export const replaceSystemDocument = replaceAdminDocument
export const deleteSystemDocument = deleteAdminDocument
