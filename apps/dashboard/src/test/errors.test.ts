import { describe, expect, it } from 'vitest'
import { isVoizyError } from '@/lib/latency'

describe('isVoizyError', () => {
  it('accepts a message from the worker', () => {
    expect(isVoizyError({ type: 'error', message: 'Quota used up.' })).toBe(true)
  })
  it('rejects anything else, including oversized or empty messages', () => {
    for (const bad of [null, 'x', 5, {}, { type: 'turn_latency' }, { type: 'error' }, { type: 'error', message: '' }, { type: 'error', message: 'x'.repeat(601) }, { type: 'error', message: 5 }]) {
      expect(isVoizyError(bad)).toBe(false)
    }
  })
})
