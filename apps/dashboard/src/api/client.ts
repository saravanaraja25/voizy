import type {
  AgentConfig,
  AgentOut,
  CatalogOut,
  MeOut,
  TestSessionOut,
  VersionOut,
  VersionSummary,
} from './types'

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `request failed (${status})`)
    this.status = status
    this.detail = detail
  }
}

/** Pydantic validation errors -> { 'turn.vad_min_silence_ms': 'message' }, ignoring the request wrapper. */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || error.status !== 422 || !Array.isArray(error.detail)) {
    return {}
  }
  const out: Record<string, string> = {}
  for (const item of error.detail as Array<{ loc?: unknown[]; msg?: string }>) {
    // 'http'/'builtin' are discriminated-union tags pydantic inserts into tool paths.
    const path = (item.loc ?? [])
      .filter((p) => p !== 'body' && p !== 'config' && p !== 'http' && p !== 'builtin')
      .join('.')
    if (!(path in out)) out[path] = item.msg ?? 'invalid value'
  }
  return out
}

export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 422) {
      const errs = Object.entries(fieldErrors(error))
      if (errs.length) return errs.map(([k, v]) => (k ? `${k}: ${v}` : v)).join('; ')
    }
    if (error.status === 403) return 'You do not have permission to do that.'
    return error.message
  }
  return error instanceof Error ? error.message : 'Something went wrong.'
}

export type Client = ReturnType<typeof createClient>

export function createClient(baseUrl: string, key: string, onUnauthorized?: () => void) {
  const root = baseUrl.replace(/\/+$/, '')

  async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await fetch(`${root}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${key}`,
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    if (res.status === 401) onUnauthorized?.()
    if (res.status === 204) return undefined as T
    const text = await res.text()
    let data: unknown
    try {
      data = text ? JSON.parse(text) : undefined
    } catch {
      data = text
    }
    if (!res.ok) {
      const detail = (data as { detail?: unknown } | undefined)?.detail ?? data
      throw new ApiError(res.status, detail)
    }
    return data as T
  }

  return {
    me: () => request<MeOut>('GET', '/v1/me'),
    catalog: () => request<CatalogOut>('GET', '/v1/catalog'),
    listAgents: () => request<AgentOut[]>('GET', '/v1/agents'),
    getAgent: (id: string) => request<AgentOut>('GET', `/v1/agents/${id}`),
    createAgent: (name: string, config: AgentConfig) =>
      request<AgentOut>('POST', '/v1/agents', { name, config }),
    listVersions: (id: string) => request<VersionSummary[]>('GET', `/v1/agents/${id}/versions`),
    getVersion: (id: string, version: number) =>
      request<VersionOut>('GET', `/v1/agents/${id}/versions/${version}`),
    createVersion: (id: string, config: AgentConfig) =>
      request<VersionOut>('POST', `/v1/agents/${id}/versions`, { config }),
    publish: (id: string, version: number) =>
      request<AgentOut>('POST', `/v1/agents/${id}/versions/${version}/publish`),
    testSession: (id: string, version: number) =>
      request<TestSessionOut>('POST', `/v1/agents/${id}/versions/${version}/test-session`),
  }
}
