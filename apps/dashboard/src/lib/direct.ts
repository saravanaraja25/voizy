/** Mirror of voizy_core.domain.direct: which components can use the workspace's own provider key. */
export const DIRECT_PROVIDERS: Record<'stt' | 'llm' | 'tts', Record<string, string>> = {
  stt: { deepgram: 'Deepgram' },
  llm: { openai: 'OpenAI', google: 'Google AI' },
  tts: { cartesia: 'Cartesia' },
}

export type Connection = 'livekit' | 'own'
export type Kind = 'stt' | 'llm' | 'tts'

export const supportsOwnKey = (kind: Kind, provider: string) => provider in DIRECT_PROVIDERS[kind]
