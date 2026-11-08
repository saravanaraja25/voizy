export interface TurnLatency {
  id: number
  ms: Record<string, number>
}

export interface Segment {
  key: string
  label: string
  ms: number
  className: string
}

/** The stages a caller waits through, in order. transcription_delay overlaps end-of-turn, so it is not stacked. */
export function breakdown(ms: Record<string, number>): { segments: Segment[]; total: number } {
  const spec: Array<[string, string, string]> = [
    ['end_of_turn_delay', 'Turn detection', 'bg-sky-500'],
    ['llm_ttft', 'LLM', 'bg-violet-500'],
    ['tool_time', 'Tools', 'bg-amber-500'],
    ['tts_ttfb', 'Speech', 'bg-emerald-500'],
  ]
  const segments = spec
    .map(([key, label, className]) => ({ key, label, ms: ms[key] ?? 0, className }))
    .filter((s) => s.ms > 0)
  const total = ms.e2e ?? segments.reduce((sum, s) => sum + s.ms, 0)
  return { segments, total }
}

export const TARGET_MS = 800

export function isTurnLatency(v: unknown): v is { type: 'turn_latency'; ms: Record<string, number> } {
  if (typeof v !== 'object' || v === null) return false
  const o = v as { type?: unknown; ms?: unknown }
  if (o.type !== 'turn_latency' || typeof o.ms !== 'object' || o.ms === null) return false
  return Object.values(o.ms).every((n) => typeof n === 'number' && Number.isFinite(n))
}
