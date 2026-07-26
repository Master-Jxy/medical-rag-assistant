<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  disabled: Boolean,
  running: Boolean,
  references: { type: Array, default: () => [] },
})
const emit = defineEmits(['send', 'stop', 'remove-reference'])
const value = ref('')
const canSend = computed(() => value.value.trim() && !props.disabled)

function submit() {
  const content = value.value.trim()
  if (!content || props.disabled) return
  emit('send', content)
  value.value = ''
}
</script>

<template>
  <form class="composer" @submit.prevent="submit">
    <label for="agent-message">给资料Agent发送任务</label>
    <div v-if="references.length" class="references" aria-label="本轮显式引用">
      <button
        v-for="item in references"
        :key="item.key"
        type="button"
        :aria-label="`移除引用 ${item.label}`"
        @click="$emit('remove-reference', item)"
      >
        @ {{ item.label }} ×
      </button>
    </div>
    <textarea
      id="agent-message"
      v-model="value"
      maxlength="4000"
      rows="3"
      placeholder="例如：基于刚才的来源，比较两份资料并生成学习报告"
    />
    <div>
      <small>{{ value.length }}/4000</small>
      <el-button v-if="running" type="danger" @click="$emit('stop')">停止</el-button>
      <el-button type="primary" native-type="submit" :disabled="!canSend">发送</el-button>
    </div>
  </form>
</template>

<style scoped>
.composer { position: absolute; z-index: 4; left: 18px; right: 18px; bottom: 16px; padding: 12px; background: #fff; border: 1px solid #cfdad5; border-radius: 8px; box-shadow: 0 8px 24px rgb(24 55 42 / 10%); }
.composer label { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); }
.composer .references { display: flex; flex-wrap: wrap; justify-content: flex-start; gap: 6px; margin-bottom: 6px; }
.references button { max-width: 180px; overflow: hidden; padding: 4px 7px; text-overflow: ellipsis; white-space: nowrap; border: 1px solid #cbdad3; border-radius: 999px; background: #edf6f2; color: #226347; cursor: pointer; }
.composer textarea { width: 100%; resize: none; border: 0; outline: 0; box-sizing: border-box; font: inherit; }
.composer div { display: flex; justify-content: flex-end; align-items: center; gap: 8px; }
.composer small { margin-right: auto; color: var(--muted); }
</style>
