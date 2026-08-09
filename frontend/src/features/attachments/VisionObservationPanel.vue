<script setup>
defineProps({ observations: { type: Array, default: () => [] } })
</script>

<template>
  <details v-if="observations.length" class="vision-observation-panel">
    <summary>图片识别结果 · {{ observations.length }}</summary>
    <section v-for="(item, index) in observations" :key="`${item.media_asset_id}-${index}`">
      <strong>{{ item.observation?.summary || '未获得有效图片摘要' }}</strong>
      <p v-if="item.observation?.visible_text?.length">可见文字：{{ item.observation.visible_text.slice(0, 12).join('、') }}</p>
      <p v-if="item.observation?.uncertain_content?.length">不确定内容：{{ item.observation.uncertain_content.join('、') }}</p>
      <small>识别结果仅描述图片中可见信息，不构成诊断。</small>
    </section>
  </details>
</template>

<style scoped>
.vision-observation-panel { margin-top: 10px; padding: 10px 12px; text-align: left; }
.vision-observation-panel summary { color: var(--ui-text-body, #465166); font-size: 12px; font-weight: 700; cursor: pointer; }
.vision-observation-panel section { padding: 10px 0 2px; border-top: 1px solid rgba(92,108,158,.1); }
.vision-observation-panel strong { color: var(--ui-text-primary, #1d1d1f); font-size: 12px; }
.vision-observation-panel p, .vision-observation-panel small { display: block; margin: 5px 0 0; color: var(--muted); font-size: 11px; line-height: 1.55; }
</style>
