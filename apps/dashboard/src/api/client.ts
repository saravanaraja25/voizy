import type {
  AgentConfig,
  AgentOut,
  CatalogOut,
  IntegrationOut,
  InviteCreated,
  InviteOut,
  InvitePreview,
  MeOut,
  MemberOut,
  SetupRequest,
  TestResultOut,
  TestSessionOut,
  ToolSecretOut,
  ToolSecretPut,
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
    // 403 carries real reasons now (wrong password, rank rules, bad setup token): show them.
    if (error.status === 403 && error.message === 'missing permission') {
      return 'You do not have permission to do that.'
    }
    return error.message
  }
  return error instanceof Error ? error.message : 'Something went wrong.'
}

export type Client = ReturnType<typeof createClient>

export interface ClientOptions {
  /** Empty means same origin (the dev server proxies /v1; production sits behind one proxy). */
  baseUrl?: string
  /** Extra headers, e.g. an API key for scripts and tests. Browsers use the session cookie. */
  headers?: Record<string, string>
  /** The current session's CSRF token, sent on every write. */
  getCsrf?: () => string | null
  /** Called when the server says the session is gone. */
  onUnauthorized?: () => void
}

const WRITES = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

export function createClient(options: ClientOptions = {}) {
  const root = (options.baseUrl ?? '').replace(/\/+$/, '')

  async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = { ...options.headers }
    if (body !== undefined) headers['Content-Type'] = 'application/json'
    const csrf = options.getCsrf?.()
    if (WRITES.has(method) && csrf) headers['X-CSRF-Token'] = csrf

    const res = await fetch(`${root}${path}`, {
      method,
      headers,
      credentials: 'include',
      body: body === undefined ? undefined : JSON.stringify(body),
    })
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
      if (res.status === 401 && !path.startsWith('/v1/auth/') && path !== '/v1/me') {
        options.onUnauthorized?.()
      }
      throw new ApiError(res.status, detail)
    }
    return data as T
  }

  return {
    // session
    setupStatus: () => request<{ needs_setup: boolean }>('GET', '/v1/setup/status'),
    setup: (body: SetupRequest) => request<MeOut>('POST', '/v1/setup', body),
    login: (email: string, password: string) =>
      request<MeOut>('POST', '/v1/auth/login', { email, password }),
    logout: () => request<{ detail: string }>('POST', '/v1/auth/logout'),
    changePassword: (current_password: string, new_password: string) =>
      request<{ detail: string }>('POST', '/v1/auth/password', { current_password, new_password }),
    me: () => request<MeOut>('GET', '/v1/me'),
    // team
    members: () => request<MemberOut[]>('GET', '/v1/members'),
    removeMember: (userId: string) => request<void>('DELETE', `/v1/members/${userId}`),
    invites: () => request<InviteOut[]>('GET', '/v1/invites'),
    // Invitations are superadmin-only for now, so an email is all the server needs.
    createInvite: (email: string) => request<InviteCreated>('POST', '/v1/invites', { email }),
    revokeInvite: (id: string) => request<void>('DELETE', `/v1/invites/${id}`),
    previewInvite: (token: string) =>
      request<InvitePreview>('GET', `/v1/invites/${encodeURIComponent(token)}`),
    acceptInvite: (token: string, display_name: string, password: string) =>
      request<MeOut>('POST', `/v1/invites/${encodeURIComponent(token)}/accept`, {
        display_name,
        password,
      }),
    // integrations and tool credentials (write-only: no response ever carries a secret value)
    integrations: () => request<IntegrationOut[]>('GET', '/v1/integrations'),
    saveIntegration: (id: string, values: Record<string, string>) =>
      request<IntegrationOut>('PUT', `/v1/integrations/${id}`, { values }),
    removeIntegration: (id: string) => request<void>('DELETE', `/v1/integrations/${id}`),
    testIntegration: (id: string) => request<TestResultOut>('POST', `/v1/integrations/${id}/test`),
    toolSecrets: () => request<ToolSecretOut[]>('GET', '/v1/secrets'),
    putToolSecret: (name: string, body: ToolSecretPut) =>
      request<ToolSecretOut>('PUT', `/v1/secrets/${encodeURIComponent(name)}`, body),
    deleteToolSecret: (name: string) =>
      request<void>('DELETE', `/v1/secrets/${encodeURIComponent(name)}`),
    // agents
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
