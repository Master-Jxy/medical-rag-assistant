<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { getMediaPreview } from '../../api/media.js'

const props = defineProps({ attachments: { type: Array, default: () => [] } })
const previews = ref([])

function clear() {
  for (const item of previews.value) {
    if (item.ownedUrl && globalThis.URL?.revokeObjectURL) URL.revokeObjectURL(item.url)
  }
  previews.value = []
}

watch(() => props.attachments, async (attachments) => {
  clear()
  const next = []
  for (const attachment of attachments || []) {
    if (attachment.localUrl) {
      next.push({ ...attachment, url: attachment.localUrl, ownedUrl: true })
      continue
    }
    try {
      const blob = await getMediaPreview(attachment.media_asset_id || attachment.id)
      next.push({ ...attachment, url: URL.createObjectURL(blob), ownedUrl: true })
    } catch {
      next.push({ ...attachment, url: '', ownedUrl: false, failed: true })
    }
  }
  previews.value = next
}, { immediate: true, deep: true })

onBeforeUnmount(clear)
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
.private-attachment-gallery figure { width: min(180px, 46vw); margin: 0; text-align: left; }
.private-attachment-gallery img, .preview-failed { width: 100%; height: 128px; display: grid; place-items: center; object-fit: cover; border: 1px solid rgba(92,108,158,.14); border-radius: 13px; background: rgba(238,241,247,.82); color: var(--muted); font-size: 11px; }
.private-attachment-gallery figcaption { margin-top: 4px; overflow: hidden; color: var(--muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
</style>
