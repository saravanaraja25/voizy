import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { agent, me, mockApi, renderAt, signInStored, versionOut } from './harness'

describe('agents list', () => {
  it('shows an empty state with a create action', async () => {
    signInStored()
    mockApi({ 'GET /v1/me': { body: me() }, 'GET /v1/agents': { body: [] } })
    renderAt('/')
    expect(await screen.findByText(/no agents yet/i)).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /new agent/i }).length).toBeGreaterThan(0)
  })

  it('lists agents with live and draft status', async () => {
    signInStored()
    mockApi({
      'GET /v1/me': { body: me() },
      'GET /v1/agents': {
        body: [agent({ id: 'a1', name: 'Front desk', published_version: 3 }), agent({ id: 'a2', name: 'Sales' })],
      },
    })
    renderAt('/')
    const live = await screen.findByRole('link', { name: 'Front desk' })
    expect(live).toHaveAttribute('href', '/agents/a1')
    expect(screen.getByText('Live · v3')).toBeInTheDocument()
    expect(screen.getByText('Draft')).toBeInTheDocument()
  })

  it('hides creation when the key lacks the permission', async () => {
    signInStored()
    mockApi({ 'GET /v1/me': { body: me(['agents:read']) }, 'GET /v1/agents': { body: [] } })
    renderAt('/')
    await screen.findByText(/no agents yet/i)
    expect(screen.queryByRole('button', { name: /new agent/i })).not.toBeInTheDocument()
  })

  it('reports load failures and lets the user retry', async () => {
    signInStored()
    let attempt = 0
    mockApi({
      'GET /v1/me': { body: me() },
      'GET /v1/agents': () => (attempt++ === 0 ? { status: 500, body: { detail: 'database is down' } } : { body: [agent()] }),
    })
    renderAt('/')
    expect(await screen.findByText(/could not load agents/i)).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: /retry/i }))
    expect(await screen.findByRole('link', { name: 'Front desk' })).toBeInTheDocument()
  })

  it('creates an agent from the template and opens it', async () => {
    signInStored()
    const calls = mockApi({
      'GET /v1/me': { body: me() },
      'GET /v1/agents': { body: [] },
      'GET /v1/catalog': { body: { stt: [], llm: [], tts: [], default_voice_id: 'v1' } },
      'POST /v1/agents': { status: 201, body: agent({ id: 'new1', name: 'Reception' }) },
      'GET /v1/agents/new1': { body: agent({ id: 'new1', name: 'Reception' }) },
      'GET /v1/agents/new1/versions': {
        body: [{ version: 1, is_published: false, published_at: null, created_at: '2026-11-01T10:00:00Z' }],
      },
      'GET /v1/agents/new1/versions/1': { body: versionOut(1) },
    })
    renderAt('/')
    const user = userEvent.setup()
    await user.click((await screen.findAllByRole('button', { name: /new agent/i }))[0]!)
    await user.type(await screen.findByLabelText('Name'), '  Reception ')
    await user.click(screen.getByRole('button', { name: /create agent/i }))

    const post = calls.find((c) => c.method === 'POST' && c.path === '/v1/agents')!
    const body = post.body as { name: string; config: { name: string; mode: string; system_prompt: string } }
    expect(body.name).toBe('Reception')
    expect(body.config).toMatchObject({ name: 'Reception', mode: 'pipeline' })
    expect(body.config.system_prompt).toContain('{{company}}')
    await screen.findByRole('heading', { name: 'Reception' })
    expect(window.location.pathname).toBe('/agents/new1')
  })
})
