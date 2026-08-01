<script setup>
import { X } from '@lucide/vue'

defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, required: true },
  description: { type: String, default: '' },
  width: { type: String, default: '560px' },
})

const emit = defineEmits(['close'])
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" @click.self="emit('close')">
      <section class="modal-dialog" role="dialog" aria-modal="true" :aria-label="title" :style="{ '--dialog-width': width }">
        <header>
          <div><h2>{{ title }}</h2><p v-if="description">{{ description }}</p></div>
          <button class="icon-button" type="button" aria-label="关闭" @click="emit('close')"><X :size="17" /></button>
        </header>
        <div class="modal-body"><slot /></div>
        <footer v-if="$slots.footer"><slot name="footer" /></footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-backdrop { position: fixed; inset: 0; z-index: 100; display: grid; place-items: center; padding: 20px; background: rgba(12, 18, 17, .52); }
.modal-dialog { width: min(var(--dialog-width), 100%); max-height: min(88vh, 900px); display: flex; flex-direction: column; border: 1px solid var(--border-default); border-radius: 8px; background: var(--bg-surface); box-shadow: 0 22px 60px rgba(12,18,17,.24); overflow: hidden; }
.modal-dialog > header { flex: 0 0 auto; display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; padding: 17px 18px; border-bottom: 1px solid var(--border-default); }
.modal-dialog h2 { margin: 0; color: var(--text-strong); font-size: 16px; line-height: 23px; letter-spacing: 0; }
.modal-dialog header p { margin: 3px 0 0; color: var(--text-muted); font-size: 11px; line-height: 18px; }
.modal-body { min-height: 0; overflow: auto; padding: 18px; }
.modal-dialog > footer { flex: 0 0 auto; display: flex; justify-content: flex-end; gap: 8px; padding: 12px 18px; border-top: 1px solid var(--border-default); background: var(--bg-subtle); }
</style>
