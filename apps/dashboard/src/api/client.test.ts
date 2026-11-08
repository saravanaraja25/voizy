import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, createClient, describeError, fieldErrors } from './client'
import { normalizeBaseUrl } from '@/auth/session'

afterEach(() => vi.restoreAllMocks())

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue(
    new Response(body === undefined ? null : JSON.stringify(body), { status }),
  )
  vi.stubGlobal('fetch', fn)
  return fn
}

describe('client', () => {
  it('sends the bearer key and JSON body, and trims the base url', async () => {
    const fn = mockFetch(200, { ok: true })
    await createClient('http://localhost:8010/', 'vz_key').createVersion('a1', { name: 'x' } as never)
    const [url, init] = fn.mock.calls[0]!
    expect(url).toBe('http://localhost:8010/v1/agents/a1/versions')
    expect(init.headers.Authorization).toBe('Bearer vz_key')
    expect(init.headers['Content-Type']).toBe('application/json')
    expect(JSON.parse(init.body)).toEqual({ config: { name: 'x' } })
  })

  it('does not send a content type on bodyless requests', async () => {
    const fn = mockFetch(200, [])
    await createClient('http://x', 'k').listAgents()
    expect(fn.mock.calls[0]![1].headers['Content-Type']).toBeUndefined()
  })

  it('signs out on 401 and throws ApiError', async () => {
    mockFetch(401, { detail: 'invalid or missing credentials' })
    const onUnauthorized = vi.fn()
    await expect(createClient('http://x', 'k', onUnauthorized).me()).rejects.toBeInstanceOf(ApiError)
    expect(onUnauthorized).toHaveBeenCalledOnce()
  })

  it('surfaces the server message for 4xx errors', async () => {
    mockFetch(409, { detail: 'agent is archived' })
    await expect(createClient('http://x', 'k').publish('a', 1)).rejects.toMatchObject({
      status: 409,
      message: 'agent is archived',
    })
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
    expect(describeError('weird')).toBe('Something went wrong.')
  })
})

describe('normalizeBaseUrl', () => {
  it.each([
    ['http://localhost:8010/', 'http://localhost:8010'],
    ['https://api.example.com/path', 'https://api.example.com'],
    ['http://127.0.0.1:8000', 'http://127.0.0.1:8000'],
  ])('accepts %s', (input, expected) => expect(normalizeBaseUrl(input)).toBe(expected))

  it.each(['http://api.example.com', 'ftp://x', 'javascript:alert(1)', 'not a url', ''])(
    'rejects %s',
    (input) => expect(normalizeBaseUrl(input)).toBeNull(),
  )
})
