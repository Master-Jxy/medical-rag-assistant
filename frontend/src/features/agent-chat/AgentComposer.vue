<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  disabled: Boolean,
  running: Boolean,
  references: { type: Array, default: () => [] },
})
const emit = defineEmits(['send', 'stop', 'remove-reference'])
const value = ref('')
const textarea = ref(null)
const canSend = computed(() => value.value.trim() && !props.disabled)

function focus() {
  if (!props.disabled) textarea.value?.focus()
}

defineExpose({ focus })

function submit() {
  const content = value.value.trim()
  if (!content || props.disabled) return
  emit('send', content)
  value.value = ''
}

function handleKeydown(event) {
  if (event.key !== 'Enter' || event.shiftKey) return
  event.preventDefault()
  submit()
}
</script>

<template>
  <form class="composer" @submit.prevent="submit">
    <label for="agent-message">给 Agent 发送任务</label>
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
      ref="textarea"
      id="agent-message"
      v-model="value"
      maxlength="4000"
      rows="3"
      placeholder="输入任务，Enter 发送，Shift + Enter 换行"
      :disabled="disabled"
      @keydown="handleKeydown"
    />
    <div class="composer-footer">
      <small>{{ value.length }} / 4000</small>
      <el-button v-if="running" type="danger" plain round @click="$emit('stop')">停止生成</el-button>
      <el-button v-else type="primary" round native-type="submit" :disabled="!canSend">
        发送任务
      </el-button>
    </div>
  </form>
</template>

<style scoped>
.composer {
  position: absolute;
  z-index: 4;
  right: max(18px, calc((100% - 920px) / 2));
  bottom: 10px;
  left: max(18px, calc((100% - 920px) / 2));
  padding: 10px 12px;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 8px 24px rgba(23, 32, 30, .08);
}
.composer label {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
}
.references {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 7px;
}
.references button {
  max-width: 190px;
  overflow: hidden;
  padding: 4px 8px;
  border: 1px solid #cbdad3;
  border-radius: 999px;
  color: #226347;
  background: #edf6f2;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}
.composer textarea {
  width: 100%;
  resize: none;
  border: 0;
  outline: 0;
  box-sizing: border-box;
  color: var(--ink);
  background: transparent;
  font: inherit;
  line-height: 1.6;
}
.composer textarea::placeholder { color: #9aaba7; }
.composer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 6px;
}
.composer small { color: var(--muted); }
@media (max-width: 760px) {
  .composer { right: 10px; bottom: 8px; left: 10px; }
}
</style>
