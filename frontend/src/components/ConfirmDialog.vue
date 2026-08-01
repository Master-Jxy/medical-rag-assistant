<script setup>
import { AlertTriangle, X } from '@lucide/vue'

defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, required: true },
  description: { type: String, default: '' },
  confirmText: { type: String, default: '确认' },
  cancelText: { type: String, default: '取消' },
  tone: { type: String, default: 'danger' },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['confirm', 'cancel'])
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="confirm-backdrop" @click.self="emit('cancel')">
      <section
        class="confirm-dialog"
        role="alertdialog"
        aria-modal="true"
        :aria-labelledby="`confirm-title-${tone}`"
        :aria-describedby="description ? `confirm-description-${tone}` : undefined"
      >
        <header>
          <span class="confirm-icon" :data-tone="tone"><AlertTriangle :size="18" /></span>
          <button class="icon-button" type="button" aria-label="关闭" :disabled="loading" @click="emit('cancel')">
            <X :size="17" />
          </button>
        </header>
        <h2 :id="`confirm-title-${tone}`">{{ title }}</h2>
        <p v-if="description" :id="`confirm-description-${tone}`">{{ description }}</p>
        <footer>
          <button class="dialog-button secondary" type="button" :disabled="loading" @click="emit('cancel')">{{ cancelText }}</button>
          <button class="dialog-button" :class="tone" type="button" :disabled="loading" @click="emit('confirm')">
            {{ loading ? '处理中…' : confirmText }}
          </button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.confirm-backdrop { position: fixed; inset: 0; z-index: 100; display: grid; place-items: center; padding: 20px; background: rgba(12, 18, 17, .52); }
.confirm-dialog { width: min(420px, 100%); padding: 20px; border: 1px solid var(--border-default); border-radius: 8px; background: var(--bg-surface); box-shadow: 0 22px 60px rgba(12, 18, 17, .24); }
.confirm-dialog header { display: flex; align-items: center; justify-content: space-between; }
.confirm-icon { width: 36px; height: 36px; display: grid; place-items: center; border-radius: 7px; color: var(--danger); background: #fff0ef; }
.confirm-icon[data-tone="warning"] { color: var(--warning); background: #fff7e6; }
.confirm-dialog h2 { margin: 17px 0 7px; color: var(--text-strong); font-size: 17px; line-height: 24px; letter-spacing: 0; }
.confirm-dialog p { margin: 0; color: var(--text-muted); font-size: 13px; line-height: 21px; overflow-wrap: anywhere; }
.confirm-dialog footer { display: flex; justify-content: flex-end; gap: 8px; margin-top: 22px; }
.dialog-button { min-height: 36px; padding: 0 14px; border: 1px solid transparent; border-radius: 6px; color: #fff; background: var(--danger); cursor: pointer; }
.dialog-button.warning { background: var(--warning); }
.dialog-button.secondary { color: var(--text-default); border-color: var(--border-default); background: var(--bg-surface); }
.dialog-button:disabled { cursor: wait; opacity: .62; }
</style>
