<script setup>
import { computed, onMounted, ref } from 'vue'
import { AlertTriangle, CheckCircle2, ChevronDown, FileSearch, RefreshCw, XCircle } from '@lucide/vue'

import ConfirmDialog from '../components/ConfirmDialog.vue'
import ModalDialog from '../components/ModalDialog.vue'
import { approveReview, getReviews, rejectReview } from '../api/adminPlatform'
import { getApiErrorMessage } from '../api/http'

const items = ref([])
const loading = ref(true)
const actingId = ref('')
const approveTarget = ref(null)
const rejectTarget = ref(null)
const rejectReason = ref('')
const errorMessage = ref('')
const successMessage = ref('')

const scannedRiskCount = computed(() => items.value.filter((item) => (item.parse_quality?.counts?.scanned_or_image || 0) > 0).length)

async function load() {
  loading.value = true
  errorMessage.value = ''
  try {
    items.value = (await getReviews({ status: 'pending_review' })).items
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    loading.value = false
  }
}

async function approve() {
  if (!approveTarget.value || actingId.value) return
  const item = approveTarget.value
  actingId.value = item.submission_id
  try {
    await approveReview(item.submission_id)
    approveTarget.value = null
    successMessage.value = '发布任务已完成。'
    await load()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    actingId.value = ''
  }
}

function openReject(item) {
  rejectTarget.value = item
  rejectReason.value = ''
}

async function reject() {
  if (!rejectTarget.value || rejectReason.value.trim().length < 2 || actingId.value) return
  const item = rejectTarget.value
  actingId.value = item.submission_id
  try {
    await rejectReview(item.submission_id, rejectReason.value.trim())
    rejectTarget.value = null
    successMessage.value = '资料已拒绝。'
    await load()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    actingId.value = ''
  }
}

onMounted(load)
</script>

<template>
  <section class="platform-page">
    <header class="page-toolbar">
      <div><span>REVIEW QUEUE</span><h1>审核中心</h1><p>审核解析预览，批准后才会调用向量模型并发布。</p></div>
      <button class="secondary-action" type="button" :disabled="loading" @click="load"><RefreshCw :size="15" />刷新队列</button>
    </header>
    <div class="metric-grid review-metrics">
      <article><small>待审核</small><strong>{{ items.length }}</strong><FileSearch :size="18" /></article>
      <article><small>扫描或图片风险</small><strong>{{ scannedRiskCount }}</strong><AlertTriangle :size="18" /></article>
      <article><small>发布规则</small><strong>人工批准</strong><CheckCircle2 :size="18" /></article>
    </div>
    <div v-if="successMessage" class="state-panel success">{{ successMessage }}</div>
    <div v-if="errorMessage" class="state-panel error">{{ errorMessage }}</div>
    <div v-if="loading" class="queue-empty">正在加载待审核资料…</div>
    <div v-else-if="!items.length" class="queue-empty"><CheckCircle2 :size="25" /><strong>审核队列已清空</strong><p>当前没有等待管理员处理的资料。</p></div>
    <div v-else class="review-list">
      <article v-for="item in items" :key="item.submission_id" class="review-card">
        <header>
          <div class="review-file"><span><FileSearch :size="17" /></span><div><strong :title="item.file_name">{{ item.file_name }}</strong><small>提交者 {{ item.submitter_id || '系统' }}</small></div></div>
          <span class="status-badge" data-status="pending_review">待审核</span>
        </header>
        <section class="preview-section"><small>解析预览</small><p class="preview-text">{{ item.preview_text || '无解析预览' }}</p></section>
        <div v-if="item.parse_quality?.counts" class="parse-quality">
          <span>文本页 <strong>{{ item.parse_quality.counts.text || 0 }}</strong></span>
          <span>疑似表格 <strong>{{ item.parse_quality.counts.table_like || 0 }}</strong></span>
          <span :class="{ warning: item.parse_quality.counts.scanned_or_image }">扫描风险 <strong>{{ item.parse_quality.counts.scanned_or_image || 0 }}</strong></span>
        </div>
        <details v-if="item.parse_quality?.page_results?.length" class="page-quality">
          <summary><ChevronDown :size="15" />逐页解析结果（{{ item.parse_quality.page_results.length }} 页）</summary>
          <div><p v-for="page in item.parse_quality.page_results" :key="page.page">第 {{ page.page }} 页：{{ page.kind }}，文本 {{ page.text_chars }} 字，图片对象 {{ page.image_count }}</p></div>
        </details>
        <p v-for="warning in item.parse_warnings" :key="warning" class="parse-warning"><AlertTriangle :size="14" />{{ warning }}</p>
        <footer><small>SHA-256：{{ item.content_hash }}</small><div><button class="secondary-action danger" type="button" @click="openReject(item)"><XCircle :size="15" />拒绝</button><button class="primary-action" type="button" @click="approveTarget = item"><CheckCircle2 :size="15" />批准发布</button></div></footer>
      </article>
    </div>

    <ConfirmDialog
      :open="Boolean(approveTarget)"
      tone="warning"
      title="批准并发布这份资料？"
      :description="approveTarget ? `系统将向量化“${approveTarget.file_name}”并加入公共检索集合。` : ''"
      confirm-text="批准发布"
      :loading="Boolean(actingId)"
      @cancel="approveTarget = null"
      @confirm="approve"
    />

    <ModalDialog :open="Boolean(rejectTarget)" title="拒绝资料" :description="rejectTarget?.file_name || ''" width="480px" @close="rejectTarget = null">
      <label class="reason-field"><span>拒绝原因</span><textarea v-model="rejectReason" rows="4" minlength="2" maxlength="500" placeholder="说明资料不符合发布要求的原因"></textarea><small>至少 2 个字符，提交者可看到此说明。</small></label>
      <template #footer><button class="secondary-action" type="button" :disabled="Boolean(actingId)" @click="rejectTarget = null">取消</button><button class="danger-action" type="button" :disabled="rejectReason.trim().length < 2 || Boolean(actingId)" @click="reject">{{ actingId ? '处理中…' : '确认拒绝' }}</button></template>
    </ModalDialog>
  </section>
</template>

<style scoped>
.secondary-action, .primary-action, .danger-action { min-height: 34px; display: inline-flex; align-items: center; justify-content: center; gap: 7px; padding: 0 12px; border: 1px solid var(--border-default); border-radius: 6px; color: var(--text-default); background: var(--bg-surface); cursor: pointer; font-size: 12px; }
.primary-action { color: #fff; border-color: var(--action); background: var(--action); }
.danger-action { color: #fff; border-color: var(--danger); background: var(--danger); }
.secondary-action.danger { color: var(--danger); }
.secondary-action:disabled, .primary-action:disabled, .danger-action:disabled { cursor: wait; opacity: .55; }
.review-metrics article { position: relative; }
.review-metrics article > svg { position: absolute; top: 16px; right: 16px; color: var(--text-muted); }
.review-metrics article:nth-child(2) > svg { color: var(--warning); }
.review-metrics article:nth-child(3) strong { font-size: 16px; }
.queue-empty { min-height: 260px; display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 7px; padding: 28px; border: 1px solid var(--border-default); border-radius: 8px; color: var(--text-muted); background: var(--bg-surface); text-align: center; }
.queue-empty strong { color: var(--text-strong); }
.queue-empty p { margin: 0; font-size: 12px; }
.review-file { min-width: 0; display: flex; align-items: center; gap: 10px; }
.review-file > span { width: 34px; height: 34px; flex: 0 0 34px; display: grid; place-items: center; border-radius: 6px; color: var(--brand); background: #eaf4f1; }
.review-file strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.preview-section { margin-top: 14px; }
.preview-section > small { color: var(--text-muted); font-size: 10px; font-weight: 700; }
.parse-quality { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 10px; }
.parse-quality span { padding: 5px 8px; border-radius: 5px; color: var(--text-muted); background: var(--bg-subtle); font-size: 10px; }
.parse-quality span.warning { color: #805914; background: #fff6df; }
.parse-quality strong { color: var(--text-strong); }
.page-quality { margin-top: 10px; border: 1px solid var(--border-default); border-radius: 6px; }
.page-quality summary { display: flex; align-items: center; gap: 7px; padding: 9px 10px; color: var(--text-default); cursor: pointer; font-size: 11px; }
.page-quality[open] summary svg { transform: rotate(180deg); }
.page-quality > div { max-height: 150px; overflow: auto; padding: 0 10px 8px; }
.page-quality p { margin: 5px 0; color: var(--text-muted); font-size: 10px; }
.parse-warning { display: flex; align-items: flex-start; gap: 6px; margin: 9px 0 0; color: #805914; font-size: 11px; }
.review-card footer { align-items: center; }
.review-card footer > small { max-width: 54%; overflow: hidden; color: var(--text-muted); text-overflow: ellipsis; white-space: nowrap; }
.review-card footer > div { display: flex; gap: 7px; }
.reason-field { display: grid; gap: 7px; color: var(--text-default); font-size: 12px; font-weight: 600; }
.reason-field textarea { width: 100%; padding: 10px; border: 1px solid var(--border-strong); border-radius: 6px; outline: 0; resize: vertical; }
.reason-field textarea:focus { border-color: var(--action); box-shadow: 0 0 0 3px rgba(37,99,235,.09); }
.reason-field small { color: var(--text-muted); font-size: 10px; font-weight: 400; }
@media (max-width: 640px) { .review-card footer { align-items: stretch; flex-direction: column; } .review-card footer > small { max-width: 100%; } .review-card footer > div { justify-content: flex-end; } }
</style>
