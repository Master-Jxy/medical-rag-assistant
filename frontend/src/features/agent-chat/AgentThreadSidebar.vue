<script setup>
import { LoaderCircle } from '@lucide/vue'

defineProps({
  threads: { type: Array, default: () => [] },
  selectedId: { type: String, default: '' },
  loading: Boolean,
  statusFilter: { type: String, default: 'active' },
  runningIds: { type: Array, default: () => [] },
  unreadIds: { type: Array, default: () => [] },
})
defineEmits([
  'new',
  'select',
  'rename',
  'archive',
  'restore',
  'delete',
  'show-active',
  'show-archived',
])
</script>

<template>
  <aside class="thread-sidebar" aria-label="Agent 会话列表">
    <el-button class="new-thread" type="primary" round @click="$emit('new')">
      ＋ 新建会话
    </el-button>
    <div class="status-tabs" aria-label="会话状态筛选">
      <button :class="{ active: statusFilter === 'active' }" @click="$emit('show-active')">
        进行中
      </button>
      <button :class="{ active: statusFilter === 'archived' }" @click="$emit('show-archived')">
        已归档
      </button>
    </div>
    <p class="section-label">历史会话</p>
    <div v-if="loading" class="empty">正在加载会话…</div>
    <div v-else-if="!threads.length" class="empty">
      {{ statusFilter === 'archived' ? '暂无已归档会话' : '暂无 Agent 会话' }}
    </div>
    <div
      v-for="thread in threads"
      :key="thread.id"
      class="thread-row"
      :class="{ active: selectedId === thread.id, running: runningIds.includes(thread.id) }"
      :data-thread-id="thread.id"
    >
      <button class="thread-main" @click="$emit('select', thread)">
        <span class="thread-title">
          <strong>{{ thread.title }}</strong>
          <LoaderCircle
            v-if="runningIds.includes(thread.id)"
            class="run-spinner"
            :size="14"
            aria-label="正在生成"
          />
          <i
            v-else-if="unreadIds.includes(thread.id)"
            class="unread-dot"
            aria-label="有未读回答"
          ></i>
        </span>
        <small>{{ new Date(thread.last_message_at).toLocaleString() }}</small>
      </button>
      <div class="thread-actions">
        <button :aria-label="`重命名 ${thread.title}`" @click="$emit('rename', thread)">改名</button>
        <button
          v-if="statusFilter === 'active'"
          :aria-label="`归档 ${thread.title}`"
          :disabled="runningIds.includes(thread.id)"
          :title="runningIds.includes(thread.id) ? '请先停止当前会话' : ''"
          @click="$emit('archive', thread)"
        >
          归档
        </button>
        <button v-else :aria-label="`恢复 ${thread.title}`" @click="$emit('restore', thread)">
          恢复
        </button>
        <button
          class="danger"
          :aria-label="`删除 ${thread.title}`"
          :disabled="runningIds.includes(thread.id)"
          :title="runningIds.includes(thread.id) ? '请先停止当前会话' : ''"
          @click="$emit('delete', thread)"
        >
          删除
        </button>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.thread-sidebar {
  height: 100%;
  padding: 16px;
  overflow: auto;
  box-sizing: border-box;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 8px;
}
.new-thread { width: 100%; }
.status-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  margin-top: 13px;
  padding: 3px;
  border-radius: 6px;
  background: #f0f3f1;
}
.status-tabs button {
  padding: 7px;
  border: 0;
  border-radius: 5px;
  color: var(--muted);
  background: transparent;
  cursor: pointer;
}
.status-tabs button.active {
  color: var(--primary-dark);
  background: #fff;
  font-weight: 700;
  box-shadow: 0 1px 3px rgb(20 40 31 / 10%);
}
.section-label {
  margin: 22px 8px 10px;
  color: var(--muted);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0;
}
.thread-row {
  margin-bottom: 6px;
  padding: 5px;
  border-radius: 6px;
  background: transparent;
}
.thread-row:hover { background: #f1f6f4; }
.thread-row.active { background: #e8f3ef; box-shadow: inset 2px 0 var(--brand); }
.thread-main {
  width: 100%;
  min-width: 0;
  display: grid;
  gap: 5px;
  padding: 7px;
  border: 0;
  color: inherit;
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.thread-main strong {
  overflow: hidden;
  color: var(--ink);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.thread-title { min-width: 0; display: flex; align-items: center; gap: 7px; }
.thread-title strong { min-width: 0; flex: 1; }
.run-spinner { flex: 0 0 auto; color: var(--primary); animation: thread-spin .8s linear infinite; }
.unread-dot { flex: 0 0 auto; width: 7px; height: 7px; border-radius: 50%; background: var(--action); box-shadow: 0 0 0 3px rgba(44, 103, 214, .12); }
.thread-main small, .empty { color: var(--muted); font-size: 10px; }
.thread-actions {
  display: flex;
  gap: 10px;
  max-height: 0;
  overflow: hidden;
  padding: 0 7px;
  opacity: 0;
  transition: .15s ease;
}
.thread-row:hover .thread-actions,
.thread-row:focus-within .thread-actions {
  max-height: 28px;
  padding-top: 4px;
  opacity: 1;
}
.thread-actions button {
  padding: 0;
  border: 0;
  color: var(--primary);
  background: transparent;
  font-size: 11px;
  cursor: pointer;
}
.thread-actions .danger { color: #ad5547; }
.thread-actions button:disabled { cursor: not-allowed; opacity: .45; }
.empty { padding: 26px 8px; text-align: center; }
@keyframes thread-spin { to { transform: rotate(360deg); } }
@media (max-width: 760px) {
  .thread-actions { max-height: 28px; padding-top: 4px; opacity: 1; }
}
</style>
