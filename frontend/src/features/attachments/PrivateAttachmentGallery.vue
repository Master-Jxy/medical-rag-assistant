<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { getMediaPreview } from '../../api/media.js'

const props = defineProps({ attachments: { type: Array, default: () => [] } })
const previews = ref([])
let generation = 0

function revokeOwned(items) {
  for (const item of items) {
    if (item.ownedUrl && globalThis.URL?.revokeObjectURL) URL.revokeObjectURL(item.url)
  }
}

function clear() {
  revokeOwned(previews.value)
  previews.value = []
}

watch(() => props.attachments.map((attachment) => [
  attachment.media_asset_id || attachment.id || '',
  attachment.localUrl || '',
  attachment.original_name || '',
].join(':')).join('|'), async () => {
  const currentGeneration = ++generation
  clear()
  const next = await Promise.all((props.attachments || []).map(async (attachment) => {
    if (attachment.localUrl) {
      return { ...attachment, url: attachment.localUrl, ownedUrl: true }
    }
    try {
      const blob = await getMediaPreview(attachment.media_asset_id || attachment.id)
      return { ...attachment, url: URL.createObjectURL(blob), ownedUrl: true }
    } catch {
      return { ...attachment, url: '', ownedUrl: false, failed: true }
    }
  }))
  if (currentGeneration !== generation) {
    revokeOwned(next)
    return
  }
  previews.value = next
}, { immediate: true })

onBeforeUnmount(() => {
  generation += 1
  clear()
})
</script>

<template>
  <div v-if="attachments.length" class="private-attachment-gallery" aria-label="消息图片">
    <figure v-for="item in previews" :key="item.media_asset_id || item.id">
      <img v-if="item.url" :src="item.url" :alt="item.original_name || '用户上传图片'" />
      <div v-else class="preview-failed">图片暂不可预览</div>
      <figcaption>{{ item.original_name || '图片附件' }}</figcaption>
    </figure>
  </div>
</template>

<style scoped>
.private-attachment-gallery { display: flex; flex-wrap: wrap; justify-content: inherit; gap: 8px; margin-bottom: 8px; }
.private-attachment-gallery figure { width: min(112px, 30vw); margin: 0; text-align: left; }
.private-attachment-gallery img, .preview-failed { width: 100%; height: 84px; display: grid; place-items: center; object-fit: cover; border: 1px solid rgba(92,108,158,.14); border-radius: 8px; background: rgba(238,241,247,.82); color: var(--muted); font-size: 11px; }
.private-attachment-gallery figcaption { margin-top: 4px; overflow: hidden; color: var(--muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
</style>
