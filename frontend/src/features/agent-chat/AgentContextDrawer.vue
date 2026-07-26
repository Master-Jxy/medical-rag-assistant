<script setup>
defineProps({
  sources: { type: Array, default: () => [] },
  artifacts: { type: Array, default: () => [] },
  selectedSource: { type: Object, default: null },
  referencedSourceIds: { type: Array, default: () => [] },
  referencedArtifactIds: { type: Array, default: () => [] },
})
defineEmits([
  'open-source',
  'download',
  'toggle-source-reference',
  'toggle-artifact-reference',
])
</script>

<template>
  <aside class="context-drawer" aria-label="来源与产物">
    <h2>来源与产物</h2>
    <section>
      <h3>本轮来源</h3>
      <p v-if="!sources.length" class="empty">暂无来源。</p>
      <div
        v-for="item in sources"
        :key="`${item.document_id}-${item.chunk_id || ''}-${item.page || ''}`"
        class="context-row"
      >
        <button class="context-link" @click="$emit('open-source', item)">
          {{ item.file_name || item.document_id }}
          <small v-if="item.page"> · 第{{ item.page }}页</small>
        </button>
        <button
          class="reference-button"
          @click="$emit('toggle-source-reference', item)"
        >
          {{ referencedSourceIds.includes(item.document_id) ? '取消引用' : '引用' }}
        </button>
      </div>
      <dl v-if="selectedSource">
        <dt>资料</dt><dd>{{ selectedSource.file_name }}</dd>
        <dt>版本</dt><dd>v{{ selectedSource.version }}</dd>
        <dt>分类</dt><dd>{{ selectedSource.category || '未分类' }}</dd>
        <dt>科室</dt><dd>{{ selectedSource.department || '未设置' }}</dd>
      </dl>
    </section>
    <section>
      <h3>报告产物</h3>
      <p v-if="!artifacts.length" class="empty">暂无产物。</p>
      <div v-for="item in artifacts" :key="item.id" class="context-row">
        <button class="context-link" @click="$emit('download', item)">{{ item.file_name }}</button>
        <button class="reference-button" @click="$emit('toggle-artifact-reference', item)">
          {{ referencedArtifactIds.includes(item.id) ? '取消引用' : '引用' }}
        </button>
      </div>
    </section>
  </aside>
</template>

<style scoped>
.context-drawer { height: 100%; padding: 16px; overflow: auto; background: #fff; border: 1px solid var(--border); border-radius: 8px; }
h2 { margin: 0 0 18px; font-size: 17px; }
h3 { margin: 18px 0 8px; font-size: 13px; color: #52635c; }
.context-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 5px; margin: 6px 0; }
.context-link { display: block; width: 100%; padding: 8px; overflow: hidden; text-align: left; text-overflow: ellipsis; border: 1px solid #dce5e1; border-radius: 5px; background: #f8faf9; color: #226347; cursor: pointer; }
.reference-button { padding: 6px; border: 1px dashed #b9cdc3; border-radius: 5px; background: #fff; color: #226347; cursor: pointer; }
.empty { color: var(--muted); font-size: 13px; }
dl { display: grid; grid-template-columns: 54px 1fr; gap: 6px; font-size: 13px; }
dt { color: var(--muted); }
dd { margin: 0; overflow-wrap: anywhere; }
</style>
