import { computed, onBeforeUnmount, ref } from 'vue'

import { deleteMediaAsset, uploadMediaAsset } from '../../api/media.js'
import { getApiErrorMessage } from '../../api/http.js'

const ALLOWED_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp'])
const MAX_BYTES = 10 * 1024 * 1024
const MAX_IMAGES = 3

function localUrl(file) {
  return globalThis.URL?.createObjectURL ? URL.createObjectURL(file) : ''
}

function revoke(url) {
  if (url && globalThis.URL?.revokeObjectURL) URL.revokeObjectURL(url)
}

export function useAttachmentDraft() {
  const items = ref([])
  const error = ref('')
  const uploading = computed(() => items.value.some((item) => item.status === 'uploading'))
  const hasAttachments = computed(() => items.value.length > 0)

  function addFiles(files) {
    error.value = ''
    const incoming = Array.from(files || []).filter((file) => file instanceof File)
    if (!incoming.length) return
    if (items.value.length + incoming.length > MAX_IMAGES) {
      error.value = '每条消息最多添加 3 张图片。'
      return
    }
    for (const file of incoming) {
      if (!ALLOWED_TYPES.has(file.type)) {
        error.value = '仅支持 JPG、PNG、WEBP 图片。'
        continue
      }
      if (file.size > MAX_BYTES) {
        error.value = '单张图片不能超过 10 MiB。'
        continue
      }
      items.value.push({
        key: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`,
        file,
        localUrl: localUrl(file),
        status: 'ready',
        error: '',
        assetId: '',
      })
    }
  }

  async function upload(item) {
    if (item.assetId) return item.assetId
    item.status = 'uploading'
    item.error = ''
    try {
      const asset = await uploadMediaAsset(item.file)
      item.assetId = asset.id
      item.status = 'uploaded'
      return asset.id
    } catch (uploadError) {
      item.status = 'failed'
      item.error = getApiErrorMessage(uploadError)
      throw uploadError
    }
  }

  async function uploadAll() {
    error.value = ''
    const ids = []
    for (const item of items.value) ids.push(await upload(item))
    return ids
  }

  async function remove(item) {
    const index = items.value.findIndex((candidate) => candidate.key === item.key)
    if (index < 0 || item.status === 'uploading') return
    items.value.splice(index, 1)
    revoke(item.localUrl)
    if (item.assetId) deleteMediaAsset(item.assetId).catch(() => {})
  }

  function handlePaste(event) {
    const imageFiles = Array.from(event.clipboardData?.items || [])
      .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
      .map((item) => item.getAsFile())
      .filter(Boolean)
    if (!imageFiles.length) return
    event.preventDefault()
    addFiles(imageFiles)
  }

  function snapshot() {
    return items.value.map((item, index) => ({
      id: item.assetId,
      media_asset_id: item.assetId,
      position: index + 1,
      original_name: item.file.name,
      mime_type: item.file.type,
      byte_size: item.file.size,
      localUrl: item.localUrl,
    }))
  }

  function completeSend({ preserveLocalUrls = false } = {}) {
    if (!preserveLocalUrls) {
      for (const item of items.value) revoke(item.localUrl)
    }
    items.value = []
    error.value = ''
  }

  function dispose() {
    for (const item of items.value) {
      revoke(item.localUrl)
      if (item.assetId) deleteMediaAsset(item.assetId).catch(() => {})
    }
    items.value = []
  }

  onBeforeUnmount(dispose)
  return {
    items, error, uploading, hasAttachments,
    addFiles, upload, uploadAll, remove, handlePaste, snapshot, completeSend,
  }
}
