<script setup>
import { computed, onMounted, ref } from 'vue'
import { AlertTriangle, CheckCircle2, ChevronDown, FileSearch, RefreshCw, XCircle } from '@lucide/vue'

import ConfirmDialog from '../components/ConfirmDialog.vue'
import ModalDialog from '../components/ModalDialog.vue'
import {
  acceptMetadataSuggestion,
  approveReview,
  generateMetadataSuggestion,
  getReviews,
  rejectMetadataSuggestion,
  rejectReview,
} from '../api/adminPlatform'
import { getApiErrorMessage } from '../api/http'

const items = ref([])
const loading = ref(true)
const actingId = ref('')
const approveTarget = ref(null)
const rejectTarget = ref(null)
const rejectReason = ref('')
const errorMessage = ref('')
const successMessage = ref('')
const metadataDrafts = ref({})
const metadataActionId = ref('')

const scannedRiskCount = computed(() => items.value.filter((item) => (item.parse_quality?.counts?.scanned_or_image || 0) > 0).length)

async function load() {
  loading.value = true
  errorMessage.value = ''
  try {
    items.value = (await getReviews({ status: 'pending_review' })).items
    seedMetadataDrafts()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    loading.value = false
  }
}

function seedMetadataDrafts() {
  const next = {}
  for (const item of items.value) {
    next[item.submission_id] = fieldsToDraft(item.metadata_suggestion?.confirmed_fields || item.metadata_suggestion?.suggested_fields || {})
  }
  metadataDrafts.value = next
}

function fieldsToDraft(fields) {
  return {
    department: fields.department || '',
    disease_topics: (fields.disease_topics || []).join(', '),
    document_type: fields.document_type || '',
    published_year: fields.published_year ? String(fields.published_year) : '',
    source: fields.source || '',
    review_due_at: fields.review_due_at ? String(fields.review_due_at).slice(0, 10) : '',
  }
}

function draftToFields(item) {
  const draft = metadataDrafts.value[item.submission_id] || fieldsToDraft({})
  return {
    department: draft.department.trim() || null,
    disease_topics: draft.disease_topics.split(',').map((topic) => topic.trim()).filter(Boolean),
    document_type: draft.document_type.trim() || null,
    published_year: draft.published_year ? Number(draft.published_year) : null,
    source: draft.source.trim() || null,
    review_due_at: draft.review_due_at ? `${draft.review_due_at}T00:00:00Z` : null,
  }
}

function displayValue(value) {
  if (Array.isArray(value)) return value.length ? value.join(', ') : 'none'
  return value || 'none'
}

function suggestionConfidence(suggestion, field) {
  const value = suggestion?.confidence?.[field]
  if (typeof value !== 'number') return 'n/a'
  return `${Math.round(value * 100)}%`
}

async function generateSuggestion(item) {
  if (!item || metadataActionId.value) return
  metadataActionId.value = item.submission_id
  errorMessage.value = ''
  try {
    await generateMetadataSuggestion(item.submission_id)
    successMessage.value = 'Metadata suggestion generated.'
    await load()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    metadataActionId.value = ''
  }
}

async function acceptSuggestion(item, useOriginal = false) {
  const suggestion = item.metadata_suggestion
  if (!suggestion || metadataActionId.value) return
  metadataActionId.value = item.submission_id
  errorMessage.value = ''
  try {
    await acceptMetadataSuggestion(item.submission_id, {
      revision: suggestion.revision,
      ...(useOriginal ? {} : { fields: draftToFields(item) }),
    })
    successMessage.value = useOriginal ? 'Metadata suggestion accepted.' : 'Metadata confirmation saved.'
    await load()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    metadataActionId.value = ''
  }
}

async function rejectSuggestion(item) {
  const suggestion = item.metadata_suggestion
  if (!suggestion || metadataActionId.value) return
  metadataActionId.value = item.submission_id
  errorMessage.value = ''
  try {
    await rejectMetadataSuggestion(item.submission_id, {
      revision: suggestion.revision,
      reason: 'admin rejected metadata suggestion',
    })
    successMessage.value = 'Metadata suggestion rejected.'
    await load()
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    metadataActionId.value = ''
  }
}

async function approve() {
  if (!approveTarget.value || actingId.value) return
  const item = approveTarget.value
  actingId.value = item.submission_id
  try {
    await approveReview(item.submission_id)
    approveTarget.value = null
    successMessage.value = 'Published.'
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
    successMessage.value = 'Rejected.'
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
      <div>
        <span>REVIEW QUEUE</span>
        <h1>Review center</h1>
        <p>Review parsed previews and publish only after administrator approval.</p>
      </div>
      <button class="secondary-action" type="button" :disabled="loading" @click="load">
        <RefreshCw :size="15" />Refresh
      </button>
    </header>

    <div class="metric-grid review-metrics">
      <article><small>Pending</small><strong>{{ items.length }}</strong><FileSearch :size="18" /></article>
      <article><small>Scan/Image risk</small><strong>{{ scannedRiskCount }}</strong><AlertTriangle :size="18" /></article>
      <article><small>Publish rule</small><strong>Manual approval</strong><CheckCircle2 :size="18" /></article>
    </div>

    <div v-if="successMessage" class="state-panel success">{{ successMessage }}</div>
    <div v-if="errorMessage" class="state-panel error">{{ errorMessage }}</div>
    <div v-if="loading" class="queue-empty">Loading reviews...</div>
    <div v-else-if="!items.length" class="queue-empty">
      <CheckCircle2 :size="25" />
      <strong>No pending reviews</strong>
      <p>The queue is currently empty.</p>
    </div>

    <div v-else class="review-list">
      <article v-for="item in items" :key="item.submission_id" class="review-card">
        <header>
          <div class="review-file">
            <span><FileSearch :size="17" /></span>
            <div>
              <strong :title="item.file_name">{{ item.file_name }}</strong>
              <small>Submitter {{ item.submitter_id || 'system' }}</small>
            </div>
          </div>
          <span class="status-badge" data-status="pending_review">pending_review</span>
        </header>

        <section class="preview-section">
          <small>PREVIEW</small>
          <p class="preview-text">{{ item.preview_text || 'No parsed preview.' }}</p>
        </section>

        <div v-if="item.parse_quality?.counts" class="parse-quality">
          <span>Text <strong>{{ item.parse_quality.counts.text || 0 }}</strong></span>
          <span>Table-like <strong>{{ item.parse_quality.counts.table_like || 0 }}</strong></span>
          <span :class="{ warning: item.parse_quality.counts.scanned_or_image }">Scan risk <strong>{{ item.parse_quality.counts.scanned_or_image || 0 }}</strong></span>
        </div>

        <details v-if="item.parse_quality?.page_results?.length" class="page-quality">
          <summary><ChevronDown :size="15" />Page parse results ({{ item.parse_quality.page_results.length }})</summary>
          <div>
            <p v-for="page in item.parse_quality.page_results" :key="page.page">Page {{ page.page }}: {{ page.kind }}, text {{ page.text_chars }}, images {{ page.image_count }}</p>
          </div>
        </details>

        <p v-for="warning in item.parse_warnings" :key="warning" class="parse-warning">
          <AlertTriangle :size="14" />{{ warning }}
        </p>

        <section v-if="!item.metadata_suggestion" class="metadata-governance metadata-empty">
          <div class="metadata-heading">
            <div><small>METADATA</small><strong>Metadata suggestion</strong></div>
            <span class="status-badge" data-status="empty">empty</span>
          </div>
          <p>No suggestion has been generated yet.</p>
          <div class="metadata-actions">
            <button class="primary-action" type="button" :disabled="Boolean(metadataActionId)" @click="generateSuggestion(item)">Generate</button>
          </div>
        </section>

        <section v-else-if="metadataDrafts[item.submission_id]" class="metadata-governance">
          <div class="metadata-heading">
            <div><small>METADATA</small><strong>Metadata suggestion</strong></div>
            <span class="status-badge" :data-status="item.metadata_suggestion.status">{{ item.metadata_suggestion.status }}</span>
          </div>
          <div v-if="item.metadata_suggestion.failure_reason" class="metadata-warning">
            <AlertTriangle :size="14" />{{ item.metadata_suggestion.failure_reason }}
          </div>

          <div class="metadata-grid">
            <label><span>Department</span><small>Suggested: {{ displayValue(item.metadata_suggestion.suggested_fields.department) }} · {{ suggestionConfidence(item.metadata_suggestion, 'department') }}</small><input v-model="metadataDrafts[item.submission_id].department" :disabled="item.metadata_suggestion.status !== 'suggested'" maxlength="100" /></label>
            <label><span>Topics</span><small>Suggested: {{ displayValue(item.metadata_suggestion.suggested_fields.disease_topics) }} · {{ suggestionConfidence(item.metadata_suggestion, 'disease_topics') }}</small><input v-model="metadataDrafts[item.submission_id].disease_topics" :disabled="item.metadata_suggestion.status !== 'suggested'" maxlength="500" /></label>
            <label><span>Document type</span><small>Suggested: {{ displayValue(item.metadata_suggestion.suggested_fields.document_type) }} · {{ suggestionConfidence(item.metadata_suggestion, 'document_type') }}</small><input v-model="metadataDrafts[item.submission_id].document_type" :disabled="item.metadata_suggestion.status !== 'suggested'" maxlength="80" /></label>
            <label><span>Year</span><small>Suggested: {{ displayValue(item.metadata_suggestion.suggested_fields.published_year) }} · {{ suggestionConfidence(item.metadata_suggestion, 'published_year') }}</small><input v-model="metadataDrafts[item.submission_id].published_year" :disabled="item.metadata_suggestion.status !== 'suggested'" type="number" min="1900" max="2100" /></label>
            <label><span>Source</span><small>Suggested: {{ displayValue(item.metadata_suggestion.suggested_fields.source) }} · {{ suggestionConfidence(item.metadata_suggestion, 'source') }}</small><input v-model="metadataDrafts[item.submission_id].source" :disabled="item.metadata_suggestion.status !== 'suggested'" maxlength="255" /></label>
            <label><span>Review due</span><small>Suggested: {{ displayValue(item.metadata_suggestion.suggested_fields.review_due_at?.slice?.(0, 10)) }} · {{ suggestionConfidence(item.metadata_suggestion, 'review_due_at') }}</small><input v-model="metadataDrafts[item.submission_id].review_due_at" :disabled="item.metadata_suggestion.status !== 'suggested'" type="date" /></label>
          </div>

          <details v-if="item.metadata_suggestion.evidence.length" class="metadata-evidence">
            <summary><ChevronDown :size="15" />Evidence ({{ item.metadata_suggestion.evidence.length }})</summary>
            <p v-for="evidence in item.metadata_suggestion.evidence" :key="`${evidence.field || 'all'}-${evidence.snippet}`">{{ evidence.field || 'overall' }}: {{ evidence.snippet }}</p>
          </details>

          <p v-for="warning in item.metadata_suggestion.parse_warnings" :key="`metadata-${warning}`" class="parse-warning">
            <AlertTriangle :size="14" />{{ warning }}
          </p>

          <div class="metadata-actions">
            <button class="secondary-action" type="button" :disabled="item.metadata_suggestion.status !== 'suggested' || Boolean(metadataActionId)" @click="acceptSuggestion(item, true)">Accept original</button>
            <button class="secondary-action danger" type="button" :disabled="item.metadata_suggestion.status !== 'suggested' || Boolean(metadataActionId)" @click="rejectSuggestion(item)">Reject suggestion</button>
            <button class="primary-action" type="button" :disabled="item.metadata_suggestion.status !== 'suggested' || Boolean(metadataActionId)" @click="acceptSuggestion(item)">Save</button>
          </div>
        </section>

        <footer>
          <small>SHA-256: {{ item.content_hash }}</small>
          <div>
            <button class="secondary-action danger" type="button" @click="openReject(item)"><XCircle :size="15" />Reject</button>
            <button class="primary-action" type="button" @click="approveTarget = item"><CheckCircle2 :size="15" />Approve</button>
          </div>
        </footer>
      </article>
    </div>

    <ConfirmDialog
      :open="Boolean(approveTarget)"
      tone="warning"
      title="Approve and publish?"
      :description="approveTarget ? `The system will publish ${approveTarget.file_name} into the public knowledge base.` : ''"
      confirm-text="Approve"
      :loading="Boolean(actingId)"
      @cancel="approveTarget = null"
      @confirm="approve"
    />

    <ModalDialog :open="Boolean(rejectTarget)" title="Reject submission" :description="rejectTarget?.file_name || ''" width="480px" @close="rejectTarget = null">
      <label class="reason-field">
        <span>Reason</span>
        <textarea v-model="rejectReason" rows="4" minlength="2" maxlength="500" placeholder="Explain why this submission cannot be published."></textarea>
        <small>At least 2 characters. The submitter can see this note.</small>
      </label>
      <template #footer>
        <button class="secondary-action" type="button" :disabled="Boolean(actingId)" @click="rejectTarget = null">Cancel</button>
        <button class="danger-action" type="button" :disabled="rejectReason.trim().length < 2 || Boolean(actingId)" @click="reject">{{ actingId ? 'Working...' : 'Reject' }}</button>
      </template>
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
.metadata-governance { margin-top: 14px; padding: 12px; border: 1px solid var(--border-default); border-radius: 6px; background: var(--bg-subtle); }
.metadata-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
.metadata-heading small { display: block; color: var(--text-muted); font-size: 10px; font-weight: 700; }
.metadata-heading strong { color: var(--text-strong); font-size: 13px; }
.metadata-warning { display: flex; align-items: flex-start; gap: 6px; margin-bottom: 9px; color: #805914; font-size: 11px; }
.metadata-empty p { margin: 0; color: var(--text-muted); font-size: 11px; line-height: 1.6; }
.metadata-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 9px; }
.metadata-grid label { min-width: 0; display: grid; gap: 5px; color: var(--text-default); font-size: 11px; font-weight: 700; }
.metadata-grid small { overflow: hidden; color: var(--text-muted); font-size: 10px; font-weight: 400; text-overflow: ellipsis; white-space: nowrap; }
.metadata-grid input { min-width: 0; height: 32px; padding: 0 8px; border: 1px solid var(--border-strong); border-radius: 5px; color: var(--text-default); background: var(--bg-surface); font-size: 12px; outline: 0; }
.metadata-grid input:focus { border-color: var(--action); box-shadow: 0 0 0 3px rgba(37,99,235,.08); }
.metadata-grid input:disabled { opacity: .65; }
.metadata-evidence { margin-top: 10px; border: 1px solid var(--border-default); border-radius: 6px; background: var(--bg-surface); }
.metadata-evidence summary { display: flex; align-items: center; gap: 7px; padding: 8px 9px; color: var(--text-default); cursor: pointer; font-size: 11px; }
.metadata-evidence[open] summary svg { transform: rotate(180deg); }
.metadata-evidence p { margin: 0; padding: 0 9px 8px; color: var(--text-muted); font-size: 10px; line-height: 1.5; }
.metadata-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 7px; margin-top: 10px; }
.review-card footer { align-items: center; }
.review-card footer > small { max-width: 54%; overflow: hidden; color: var(--text-muted); text-overflow: ellipsis; white-space: nowrap; }
.review-card footer > div { display: flex; gap: 7px; }
.reason-field { display: grid; gap: 7px; color: var(--text-default); font-size: 12px; font-weight: 600; }
.reason-field textarea { width: 100%; padding: 10px; border: 1px solid var(--border-strong); border-radius: 6px; outline: 0; resize: vertical; }
.reason-field textarea:focus { border-color: var(--action); box-shadow: 0 0 0 3px rgba(37,99,235,.09); }
.reason-field small { color: var(--text-muted); font-size: 10px; font-weight: 400; }
@media (max-width: 900px) { .metadata-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 640px) { .metadata-grid { grid-template-columns: 1fr; } .metadata-heading { align-items: flex-start; flex-direction: column; } .review-card footer { align-items: stretch; flex-direction: column; } .review-card footer > small { max-width: 100%; } .review-card footer > div { justify-content: flex-end; } }
</style>
