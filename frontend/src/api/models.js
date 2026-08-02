import http from './http'

export async function getModelCatalog(surface = 'rag') {
  return (await http.get('/models', { params: { surface } })).data
}
