import type { AgentConfig, CatalogOut, HttpTool } from '@/api/types'

export const DEFAULT_PROMPT = `You are {{agent_name}}, a friendly and efficient phone assistant for {{company}}.

Speak naturally and keep every reply to one or two short sentences. Ask one question at a time.
If you do not know something, say so and offer to take a message or arrange a callback.`

/** A sensible starting point; every value is editable and validated by the API on save. */
export function newAgentConfig(name: string, catalog?: CatalogOut): AgentConfig {
  const stt = catalog?.stt[0] ?? { provider: 'deepgram', model: 'nova-3' }
  const llm = catalog?.llm[0] ?? { provider: 'google', model: 'gemini-2.5-flash' }
  const tts = catalog?.tts[0] ?? { provider: 'cartesia', model: 'sonic-turbo' }
  return {
    name,
    mode: 'pipeline',
    default_language: 'en',
    system_prompt: DEFAULT_PROMPT,
    variables: [{ name: 'company', default: 'Your Company', required: false }],
    languages: [{ code: 'en', greeting: 'Hi, thanks for calling. How can I help you today?' }],
    stt: { provider: stt.provider, model: stt.model, connection: 'livekit' },
    llm: { provider: llm.provider, model: llm.model, connection: 'livekit' },
    tts: {
      provider: tts.provider,
      model: tts.model,
      connection: 'livekit',
      voice_id: catalog?.default_voice_id ?? '',
      speed: 1,
    },
    turn: {
      vad_min_silence_ms: 550,
      vad_threshold: 0.5,
      min_endpointing_delay_ms: 300,
      max_endpointing_delay_ms: 1000,
      allow_interruptions: true,
      interruption_min_words: 1,
      preemptive_generation: true,
      backchannel: false,
      max_silence_s: 15,
      max_call_duration_s: 900,
    },
    tools: [],
  }
}

export function newHttpTool(existing: string[]): HttpTool {
  let n = existing.length + 1
  while (existing.includes(`tool_${n}`)) n += 1
  return {
    kind: 'http',
    name: `tool_${n}`,
    description: '',
    url: 'https://',
    method: 'GET',
    parameters_schema: { type: 'object', properties: {} },
    filler: {
      mode: 'auto',
      delay_ms: 600,
      still_working_after_ms: 4000,
      failure_phrase: "Sorry, I couldn't get that just now.",
      phrases: [],
    },
    speculative: false,
    timeout_s: 5,
    max_result_chars: 2000,
  }
}

export type SchemaParse = { ok: true; value: Record<string, unknown> } | { ok: false; error: string }

/** Tool parameter schemas are edited as JSON text; this keeps the editor from saving garbage. */
export function parseSchemaText(text: string): SchemaParse {
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : 'Invalid JSON' }
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return { ok: false, error: 'Must be a JSON object' }
  }
  if ((parsed as { type?: unknown }).type !== 'object') {
    return { ok: false, error: 'The schema must have "type": "object"' }
  }
  return { ok: true, value: parsed as Record<string, unknown> }
}

export function isDirty(a: AgentConfig, b: AgentConfig): boolean {
  return JSON.stringify(a) !== JSON.stringify(b)
}
