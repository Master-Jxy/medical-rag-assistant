<script setup>
import { computed } from 'vue'
import { renderMarkdown } from '../utils/markdown.js'

const props = defineProps({
  content: { type: String, default: '' },
  streaming: { type: Boolean, default: false },
})

const renderedContent = computed(() => renderMarkdown(props.content))
</script>

<template>
  <div class="markdown-output">
    <div
      class="markdown-content"
      data-testid="markdown-content"
      v-html="renderedContent"
    />
    <i v-if="streaming" class="markdown-stream-cursor" aria-hidden="true" />
  </div>
</template>

<style scoped>
.markdown-output {
  min-width: 0;
  white-space: normal;
}
.markdown-content {
  overflow-wrap: anywhere;
  word-break: normal;
}
.markdown-content :deep(> :first-child) { margin-top: 0; }
.markdown-content :deep(> :last-child) { margin-bottom: 0; }
.markdown-content :deep(p) { margin: .55em 0; }
.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3),
.markdown-content :deep(h4) {
  margin: 1em 0 .45em;
  color: inherit;
  line-height: 1.4;
}
.markdown-content :deep(h1) { font-size: 1.28em; }
.markdown-content :deep(h2) { font-size: 1.18em; }
.markdown-content :deep(h3),
.markdown-content :deep(h4) { font-size: 1.08em; }
.markdown-content :deep(strong) {
  color: inherit;
  font-weight: 800;
}
.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  margin: .6em 0;
  padding-left: 1.45em;
}
.markdown-content :deep(li + li) { margin-top: .3em; }
.markdown-content :deep(blockquote) {
  margin: .7em 0;
  padding: .15em 0 .15em .9em;
  border-left: 3px solid #9bbab1;
  color: #5f746e;
}
.markdown-content :deep(code) {
  padding: .1em .35em;
  border-radius: 4px;
  background: rgb(37 72 64 / 8%);
  font-family: Consolas, "Courier New", monospace;
  font-size: .9em;
}
.markdown-content :deep(pre) {
  max-width: 100%;
  margin: .75em 0;
  padding: .8em 1em;
  overflow-x: auto;
  border-radius: 6px;
  background: #e7efec;
  white-space: pre;
}
.markdown-content :deep(pre code) {
  padding: 0;
  background: transparent;
}
.markdown-content :deep(a) {
  color: #236f9e;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.markdown-content :deep(table) {
  display: block;
  max-width: 100%;
  margin: .75em 0;
  overflow-x: auto;
  border-collapse: collapse;
}
.markdown-content :deep(th),
.markdown-content :deep(td) {
  padding: .45em .65em;
  border: 1px solid #cbdad5;
  text-align: left;
}
.markdown-stream-cursor {
  display: inline-block;
  width: 2px;
  height: 1em;
  margin-left: 3px;
  vertical-align: -2px;
  background: var(--primary);
  animation: markdown-blink .8s infinite;
}
@keyframes markdown-blink { 50% { opacity: 0; } }
</style>
