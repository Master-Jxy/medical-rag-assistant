import { afterEach, describe, expect, it, vi } from 'vitest'

import { createUuid } from '../src/utils/uuid.js'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('createUuid', () => {
  it('uses the native secure-context implementation when available', () => {
    vi.stubGlobal('crypto', { randomUUID: () => 'native-uuid' })

    expect(createUuid()).toBe('native-uuid')
  })

  it('creates a valid version 4 UUID when randomUUID is unavailable on HTTP', () => {
    vi.stubGlobal('crypto', {
      getRandomValues(bytes) {
        bytes.fill(0)
        return bytes
      },
    })

    expect(createUuid()).toBe('00000000-0000-4000-8000-000000000000')
  })

  it('still creates a valid UUID in older browsers without Web Crypto', () => {
    vi.stubGlobal('crypto', undefined)

    expect(createUuid()).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    )
  })
})
