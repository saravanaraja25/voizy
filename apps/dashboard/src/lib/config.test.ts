import { describe, expect, it } from 'vitest'
import { breakdown, isTurnLatency } from './latency'
import { isDirty, newAgentConfig, newHttpTool, parseSchemaText } from './config'

describe('newAgentConfig', () => {
  it('builds a complete pipeline config using catalog defaults', () => {
    const cfg = newAgentConfig('Ava', {
      stt: [{ provider: 'deepgram', model: 'nova-3', label: '', note: '' }],
      llm: [{ provider: 'google', model: 'gemini-2.5-flash', label: '', note: '' }],
      tts: [{ provider: 'cartesia', model: 'sonic-turbo', label: '', note: '' }],
      default_voice_id: 'voice-1',
    })
    expect(cfg.name).toBe('Ava')
    expect(cfg.mode).toBe('pipeline')
    expect(cfg.tts?.voice_id).toBe('voice-1')
    expect(cfg.system_prompt).toContain('{{company}}')
    expect(cfg.variables?.map((v) => v.name)).toContain('company')
  })

  it('declares every variable its prompt uses (the API rejects undeclared ones)', () => {
    const cfg = newAgentConfig('Ava')
    const used = [...cfg.system_prompt.matchAll(/\{\{\s*(\w+)\s*\}\}/g)].map((m) => m[1])
    const declared = new Set((cfg.variables ?? []).map((v) => v.name))
    const system = new Set(['agent_name', 'current_time', 'caller_number', 'called_number', 'call_direction'])
    for (const name of used) expect(declared.has(name!) || system.has(name!)).toBe(true)
  })
})

describe('newHttpTool', () => {
  it('picks a unique snake_case name', () => {
    expect(newHttpTool([]).name).toBe('tool_1')
    expect(newHttpTool(['tool_1', 'tool_2']).name).toBe('tool_3')
  })
})

describe('parseSchemaText', () => {
  it('accepts an object schema', () => {
    const r = parseSchemaText('{"type":"object","properties":{"date":{"type":"string"}}}')
    expect(r.ok).toBe(true)
  })
  it.each([
    ['not json', /./],
    ['[]', /JSON object/],
    ['{"type":"string"}', /"type": "object"/],
    ['{}', /"type": "object"/],
    ['null', /JSON object/],
  ])('rejects %s', (text, message) => {
    const r = parseSchemaText(text)
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toMatch(message)
  })
})

describe('isDirty', () => {
  it('detects edits', () => {
    const a = newAgentConfig('A')
    expect(isDirty(a, structuredClone(a))).toBe(false)
    expect(isDirty(a, { ...a, name: 'B' })).toBe(true)
  })
})

describe('latency breakdown', () => {
  it('stacks stages in order and uses the reported end-to-end total', () => {
    const { segments, total } = breakdown({
      transcription_delay: 250,
      end_of_turn_delay: 450,
      llm_ttft: 480,
      tts_ttfb: 110,
      e2e: 1040,
    })
    expect(segments.map((s) => s.key)).toEqual(['end_of_turn_delay', 'llm_ttft', 'tts_ttfb'])
    expect(total).toBe(1040)
  })
  it('falls back to the sum and omits empty stages', () => {
    const { segments, total } = breakdown({ llm_ttft: 300, tts_ttfb: 100 })
    expect(segments).toHaveLength(2)
    expect(total).toBe(400)
  })
  it('validates data messages before trusting them', () => {
    expect(isTurnLatency({ type: 'turn_latency', ms: { e2e: 900 } })).toBe(true)
    for (const bad of [null, 1, {}, { type: 'x', ms: {} }, { type: 'turn_latency', ms: { e2e: 'a' } }, { type: 'turn_latency', ms: null }]) {
      expect(isTurnLatency(bad)).toBe(false)
    }
  })
})

describe('latency colours', () => {
  it('gives every stage its own distinct hue', async () => {
    const { breakdown } = await import('./latency')
    const { segments } = breakdown({ end_of_turn_delay: 1, llm_ttft: 1, tool_time: 1, tts_ttfb: 1 })
    expect(new Set(segments.map((s) => s.className)).size).toBe(4)
    expect(segments.every((s) => !s.className.includes('chart'))).toBe(true) // chart tokens are grey here
  })
})
