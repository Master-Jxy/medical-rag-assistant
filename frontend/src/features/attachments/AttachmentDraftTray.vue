<script setup>
import { RotateCcw, X } from '@lucide/vue'

defineProps({ items: { type: Array, default: () => [] } })
defineEmits(['remove', 'retry'])
</script>

<template>
  <div v-if="items.length" class="attachment-draft-tray" aria-label="待发送图片">
    <figure v-for="item in items" :key="item.key" class="draft-image" :data-status="item.status">
      <img :src="item.localUrl" :alt="item.file.name" />
      <figcaption>
        <span>{{ item.status === 'uploading' ? '上传中' : item.status === 'failed' ? '上传失败' : '待发送' }}</span>
        <button v-if="item.status === 'failed'" type="button" aria-label="重试上传" @click="$emit('retry', item)"><RotateCcw :size="14" /></button>
        <button type="button" :disabled="item.status === 'uploading'" aria-label="移除图片" @click="$emit('remove', item)"><X :size="14" /></button>
      </figcaption>
      <small v-if="item.error">{{ item.error }}</small>
    </figure>
  </div>
</template>

<style scoped>
.attachment-draft-tray { grid-column: 1 / -1; display: flex; gap: 9px; overflow-x: auto; padding: 2px 1px 4px; }
.draft-image { position: relative; width: 72px; flex: 0 0 72px; margin: 0; }
.draft-image img { width: 72px; height: 54px; display: block; object-fit: cover; border: 1px solid rgba(92,108,158,.16); border-radius: 8px; background: #eef1f5; }
.draft-image figcaption { position: absolute; right: 4px; bottom: 4px; left: 4px; display: flex; align-items: center; gap: 3px; padding: 3px 4px 3px 7px; border-radius: 8px; color: #fff; background: rgba(28,34,48,.7); font-size: 9px; backdrop-filter: blur(8px); }
.draft-image figcaption span { min-width: 0; flex: 1; }
.draft-image button { width: 24px; height: 24px; display: grid; place-items: center; padding: 0; border: 0; border-radius: 7px; color: #fff; background: rgba(255,255,255,.15); cursor: pointer; }
.draft-image button:disabled { opacity: .45; }
.draft-image small { display: block; margin-top: 4px; overflow: hidden; color: var(--ui-danger, #a03f48); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.draft-image[data-status="failed"] img { border-color: rgba(215,91,97,.55); }
</style>
