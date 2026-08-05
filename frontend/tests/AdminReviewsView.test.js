import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const platformApi = vi.hoisted(() => ({
  acceptMetadataSuggestion: vi.fn(),
  approveReview: vi.fn(),
  getReviews: vi.fn(),
  rejectMetadataSuggestion: vi.fn(),
  rejectReview: vi.fn(),
}))

vi.mock('../src/api/adminPlatform.js', () => platformApi)

import AdminReviewsView from '../src/views/AdminReviewsView.vue'

const reviewItem = {
  submission_id: 'submission-1',
  submitter_id: 'user-1',
  file_name: 'guideline.txt',
  content_hash: 'a'.repeat(64),
  size_bytes: 123,
  status: 'pending_review',
  preview_text: 'heart failure follow up',
  preview_pages: 1,
  parse_warnings: ['parse warning'],
  parse_quality: { counts: { text: 1, table_like: 0, scanned_or_image: 0 } },
  rejection_reason: null,
  failure_reason: null,
  document_id: null,
  created_at: '2026-08-06T00:00:00Z',
  updated_at: '2026-08-06T00:00:00Z',
  metadata_suggestion: {
    id: 'suggestion-1',
    submission_id: 'submission-1',
    document_id: null,
    status: 'suggested',
    suggestion_source: 'fake',
    suggested_fields: {
      department: 'cardiology',
      disease_topics: ['heart failure'],
      document_type: 'txt',
      published_year: 2025,
      source: 'user_submission',
      review_due_at: '2030-01-01T00:00:00Z',
    },
    confirmed_fields: null,
    evidence: [{ field: 'department', snippet: 'heart failure', confidence: 0.7 }],
    confidence: { department: 0.7, document_type: 0.6 },
    parse_warnings: ['metadata warning'],
    failure_reason: null,
    created_by: 'admin-1',
    reviewed_by: null,
    revision: 1,
    created_at: '2026-08-06T00:00:00Z',
    updated_at: '2026-08-06T00:00:00Z',
    reviewed_at: null,
  },
}

beforeEach(() => {
  vi.clearAllMocks()
  platformApi.getReviews.mockResolvedValue({ items: [reviewItem], total: 1 })
  platformApi.acceptMetadataSuggestion.mockResolvedValue({
    ...reviewItem.metadata_suggestion,
    status: 'edited',
    revision: 2,
  })
  platformApi.rejectMetadataSuggestion.mockResolvedValue({
    ...reviewItem.metadata_suggestion,
    status: 'rejected',
    revision: 2,
  })
})

describe('AdminReviewsView metadata governance', () => {
  it('renders metadata suggestions and submits edited confirmation values', async () => {
    const wrapper = mount(AdminReviewsView, {
      global: { stubs: { teleport: true } },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('元数据建议')
    expect(wrapper.text()).toContain('heart failure')

    const inputs = wrapper.findAll('.metadata-grid input')
    await inputs[0].setValue('neurology')
    await inputs[1].setValue('stroke, emergency')
    await inputs[2].setValue('consensus')
    await inputs[3].setValue('2026')
    await inputs[4].setValue('manual source')
    await inputs[5].setValue('2031-02-03')

    await wrapper.findAll('.metadata-actions button')[2].trigger('click')
    await flushPromises()

    expect(platformApi.acceptMetadataSuggestion).toHaveBeenCalledWith('submission-1', {
      revision: 1,
      fields: {
        department: 'neurology',
        disease_topics: ['stroke', 'emergency'],
        document_type: 'consensus',
        published_year: 2026,
        source: 'manual source',
        review_due_at: '2031-02-03T00:00:00Z',
      },
    })
  })

  it('supports accepting original suggestion and rejecting the suggestion', async () => {
    const wrapper = mount(AdminReviewsView, {
      global: { stubs: { teleport: true } },
    })
    await flushPromises()

    await wrapper.findAll('.metadata-actions button')[0].trigger('click')
    await flushPromises()
    expect(platformApi.acceptMetadataSuggestion).toHaveBeenCalledWith('submission-1', {
      revision: 1,
    })

    await wrapper.findAll('.metadata-actions button')[1].trigger('click')
    await flushPromises()
    expect(platformApi.rejectMetadataSuggestion).toHaveBeenCalledWith('submission-1', {
      revision: 1,
      reason: 'admin rejected metadata suggestion',
    })
  })
})
