import { render } from '@testing-library/react'
import { vi } from 'vitest'
import { App } from '@/App'
import { newAgentConfig } from '@/lib/config'

export const API = 'http://localhost:8010'
export const ALL_PERMISSIONS = [
  'agents:read',
  'agents:create',
  'agents:edit',
  'agents:publish',
  'agents:test',
]

export interface Call {
  method: string
  path: string
  body: unknown
  auth: string | null
}

type Reply = { status?: number; body?: unknown } | ((call: Call) => { status?: number; body?: unknown })

/** Routes "METHOD /path" to canned replies and records every request. */
export function mockApi(routes: Record<string, Reply>) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = new URL(url).pathname
      const headers = (init?.headers ?? {}) as Record<string, string>
      const call: Call = {
        method: init?.method ?? 'GET',
        path,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
        auth: headers.Authorization ?? null,
      }
      calls.push(call)
      const reply = routes[`${call.method} ${path}`]
      if (!reply) return new Response(JSON.stringify({ detail: 'not found' }), { status: 404 })
      const r = typeof reply === 'function' ? reply(call) : reply
      return new Response(r.status === 204 ? null : JSON.stringify(r.body ?? {}), { status: r.status ?? 200 })
    }),
  )
  return calls
}

export const me = (permissions = ALL_PERMISSIONS) => ({
  workspace_id: 'w1',
  workspace_name: 'Acme',
  api_key_id: 'k1',
  permissions,
})

export const agent = (over: Record<string, unknown> = {}) => ({
  id: 'a1',
  name: 'Front desk',
  published_version: null,
  archived: false,
  created_at: '2026-11-01T10:00:00Z',
  ...over,
})

export const catalog = {
  stt: [{ provider: 'deepgram', model: 'nova-3', label: 'Deepgram Nova 3', note: '' }],
  llm: [{ provider: 'google', model: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash', note: 'Fast.' }],
  tts: [{ provider: 'cartesia', model: 'sonic-turbo', label: 'Cartesia Sonic Turbo', note: '' }],
  default_voice_id: 'voice-1',
}

export const versionOut = (version: number, config = newAgentConfig('Front desk', catalog)) => ({
  version,
  is_published: false,
  published_at: null,
  created_at: '2026-11-01T10:00:00Z',
  config,
})

export function signInStored() {
  sessionStorage.setItem('voizy.session', JSON.stringify({ baseUrl: API, key: 'vz_test_key' }))
}

export function renderAt(path: string) {
  window.history.pushState({}, '', path)
  return render(<App />)
}
