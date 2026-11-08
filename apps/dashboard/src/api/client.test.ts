import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, createClient, describeError, fieldErrors } from './client'

afterEach(() => vi.restoreAllMocks())

function mockFetch(status: number, body: unknown) {
  // A fresh Response per call: a body can only be read once.
  const fn = vi
    .fn()
    .mockImplementation(async () => new Response(body === undefined ? null : JSON.stringify(body), { status }))
  vi.stubGlobal('fetch', fn)
  return fn
}

describe('client', () => {
  it('uses the cookie session: credentials included, relative URL, no bearer header', async () => {
    const fn = mockFetch(200, [])
    await createClient().listAgents()
    const [url, init] = fn.mock.calls[0]!
    expect(url).toBe('/v1/agents')
    expect(init.credentials).toBe('include')
    expect(init.headers.Authorization).toBeUndefined()
  })

  it('sends the CSRF token on writes only', async () => {
    const fn = mockFetch(200, {})
    const api = createClient({ getCsrf: () => 'csrf-1' })
    await api.listAgents()
    await api.createVersion('a1', { name: 'x' } as never)
    await api.removeMember('u1')
    expect(fn.mock.calls[0]![1].headers['X-CSRF-Token']).toBeUndefined()
    expect(fn.mock.calls[1]![1].headers['X-CSRF-Token']).toBe('csrf-1')
    expect(fn.mock.calls[2]![1].headers['X-CSRF-Token']).toBe('csrf-1')
    expect(JSON.parse(fn.mock.calls[1]![1].body)).toEqual({ config: { name: 'x' } })
  })

  it('omits the CSRF header when there is no session yet', async () => {
    const fn = mockFetch(200, {})
    await createClient({ getCsrf: () => null }).login('a@example.com', 'pw')
    expect(fn.mock.calls[0]![1].headers['X-CSRF-Token']).toBeUndefined()
  })

  it('supports an API key for scripts via extra headers, and a base url', async () => {
    const fn = mockFetch(200, {})
    await createClient({ baseUrl: 'http://api.test/', headers: { Authorization: 'Bearer vz_k' } }).me()
    const [url, init] = fn.mock.calls[0]!
    expect(url).toBe('http://api.test/v1/me')
    expect(init.headers.Authorization).toBe('Bearer vz_k')
  })

  it('reports a lost session on 401, except for the calls that are meant to 401', async () => {
    mockFetch(401, { detail: 'invalid or missing credentials' })
    const onUnauthorized = vi.fn()
    const api = createClient({ onUnauthorized })
    await expect(api.listAgents()).rejects.toBeInstanceOf(ApiError)
    expect(onUnauthorized).toHaveBeenCalledOnce()
    await expect(api.me()).rejects.toBeInstanceOf(ApiError) // "am I signed in?" is allowed to say no
    await expect(api.login('a@example.com', 'wrong')).rejects.toBeInstanceOf(ApiError)
    expect(onUnauthorized).toHaveBeenCalledOnce()
  })

  it('surfaces the server message for 4xx errors', async () => {
    mockFetch(409, { detail: 'agent is archived' })
    await expect(createClient().publish('a', 1)).rejects.toMatchObject({
      status: 409,
      message: 'agent is archived',
    })
  })

  it('encodes invite tokens in the path', async () => {
    const fn = mockFetch(200, {})
    await createClient().previewInvite('a/b?c')
    expect(fn.mock.calls[0]![0]).toBe('/v1/invites/a%2Fb%3Fc')
  })
})

describe('validation errors', () => {
  const err = new ApiError(422, [
    { loc: ['body', 'config', 'turn', 'vad_min_silence_ms'], msg: 'Input should be >= 100' },
    { loc: ['body', 'config'], msg: 'prompt uses undeclared variables: region' },
    { loc: ['body', 'config', 'turn', 'vad_min_silence_ms'], msg: 'second message ignored' },
  ])

  it('maps pydantic locations to dotted field paths', () => {
    expect(fieldErrors(err)).toEqual({
      'turn.vad_min_silence_ms': 'Input should be >= 100',
      '': 'prompt uses undeclared variables: region',
    })
  })
  it('drops union tags so tool errors map to simple paths', () => {
    const e = new ApiError(422, [{ loc: ['body', 'config', 'tools', 0, 'http', 'url'], msg: 'bad url' }])
    expect(fieldErrors(e)).toEqual({ 'tools.0.url': 'bad url' })
  })
  it('returns nothing for other errors', () => {
    expect(fieldErrors(new Error('x'))).toEqual({})
    expect(fieldErrors(new ApiError(500, 'boom'))).toEqual({})
  })
  it('describes errors for humans', () => {
    expect(describeError(err)).toContain('turn.vad_min_silence_ms: Input should be >= 100')
    expect(describeError(new ApiError(403, 'missing permission'))).toMatch(/permission/)
    expect(describeError(new ApiError(403, 'Current password is incorrect.'))).toBe(
      'Current password is incorrect.',
    )
    expect(describeError('weird')).toBe('Something went wrong.')
  })
})
