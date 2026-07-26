<script setup>
defineProps({
  threads: { type: Array, default: () => [] },
  selectedId: { type: String, default: '' },
  legacyRuns: { type: Array, default: () => [] },
  loading: Boolean,
  statusFilter: { type: String, default: 'active' },
})
defineEmits([
  'new',
  'select',
  'rename',
  'archive',
  'restore',
  'delete',
  'legacy',
  'show-active',
  'show-archived',
])
</script>

<template>
  <aside class="thread-sidebar" aria-label="Agent会话列表">
    <el-button class="new-thread" type="primary" @click="$emit('new')">新建会话</el-button>
    <div class="status-tabs" aria-label="会话状态筛选">
      <button
        :class="{ active: statusFilter === 'active' }"
        @click="$emit('show-active')"
      >
        进行中
      </button>
      <button
        :class="{ active: statusFilter === 'archived' }"
        @click="$emit('show-archived')"
      >
        已归档
      </button>
    </div>
    <div v-if="loading" class="empty">正在加载会话…</div>
    <div v-else-if="!threads.length" class="empty">
      {{ statusFilter === 'archived' ? '暂无已归档会话。' : '暂无Agent会话。' }}
    </div>
    <div v-for="thread in threads" :key="thread.id" class="thread-row">
      <button
        class="thread-main"
        :class="{ active: selectedId === thread.id }"
        @click="$emit('select', thread)"
      >
        <strong>{{ thread.title }}</strong>
        <small>{{ new Date(thread.last_message_at).toLocaleString() }}</small>
      </button>
      <div class="thread-actions">
        <button :aria-label="`重命名${thread.title}`" @click="$emit('rename', thread)">改名</button>
        <button
          v-if="statusFilter === 'active'"
          :aria-label="`归档${thread.title}`"
          @click="$emit('archive', thread)"
        >
          归档
        </button>
        <button
          v-else
          :aria-label="`恢复${thread.title}`"
          @click="$emit('restore', thread)"
        >
          恢复
        </button>
        <button class="danger" :aria-label="`删除${thread.title}`" @click="$emit('delete', thread)">删除</button>
      </div>
    </div>
    <details v-if="legacyRuns.length" class="legacy">
      <summary>旧版独立任务（{{ legacyRuns.length }}）</summary>
      <button v-for="run in legacyRuns" :key="run.id" @click="$emit('legacy', run)">
        {{ run.task }}
      </button>
    </details>
  </aside>
</template>

<style scoped>
.thread-sidebar { height: 100%; padding: 12px; overflow: auto; background: #fff; border: 1px solid var(--border); border-radius: 8px; }
.new-thread { width: 100%; }
.status-tabs { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; margin-top: 10px; padding: 3px; border-radius: 6px; background: #f0f3f1; }
.status-tabs button { padding: 6px; border: 0; border-radius: 4px; background: transparent; color: var(--muted); cursor: pointer; }
.status-tabs button.active { background: #fff; color: #226347; font-weight: 700; box-shadow: 0 1px 2px rgb(20 40 31 / 10%); }
.thread-row { margin-top: 10px; padding-bottom: 8px; border-bottom: 1px solid #edf0ee; }
.thread-main { width: 100%; padding: 10px; display: grid; gap: 5px; text-align: left; border: 1px solid transparent; border-radius: 6px; background: #f7f9f8; cursor: pointer; }
.thread-main.active { border-color: var(--primary); background: #eef7f3; }
.thread-main strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.thread-main small, .empty { color: var(--muted); }
.thread-actions { display: flex; gap: 8px; padding: 6px 4px 0; }
.thread-actions button, .legacy button { border: 0; background: none; color: var(--primary); cursor: pointer; font-size: 12px; }
.thread-actions .danger { color: #b42318; }
.legacy { margin-top: 18px; color: var(--muted); }
.legacy button { display: block; width: 100%; padding: 8px 0; text-align: left; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.empty { padding: 28px 8px; text-align: center; }
</style>
