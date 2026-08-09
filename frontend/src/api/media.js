import http from './http.js'

export async function uploadMediaAsset(file) {
  const form = new FormData()
  form.append('file', file, file.name)
  return (await http.post('/media/assets', form)).data
}

export async function deleteMediaAsset(assetId) {
  return (await http.delete(`/media/assets/${encodeURIComponent(assetId)}`)).data
}

export async function getMediaPreview(assetId) {
  return (await http.get(
    `/media/assets/${encodeURIComponent(assetId)}/preview`,
    { responseType: 'blob' },
  )).data
}
