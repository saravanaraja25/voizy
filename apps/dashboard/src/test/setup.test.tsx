import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { agent, me, mockApi, renderAt, signedOut } from './harness'

async function fill(over: Partial<Record<string, string>> = {}) {
  const v = {
    token: 'tok-from-server-log',
    workspace: 'Acme',
    name: 'Olivia Owner',
    email: 'olivia@example.com',
    password: 'correct horse battery',
    confirm: 'correct horse battery',
    ...over,
  }
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('Setup token'), v.token)
  await user.type(screen.getByLabelText('Workspace name'), v.workspace)
  await user.type(screen.getByLabelText('Your name'), v.name)
  await user.type(screen.getByLabelText('Email'), v.email)
  await user.type(screen.getByLabelText('Password'), v.password)
  await user.type(screen.getByLabelText('Confirm password'), v.confirm)
  await user.click(screen.getByRole('button', { name: /create workspace/i }))
}

describe('first-run setup', () => {
  it('creates the workspace, signs in the owner, and lands on agents', async () => {
    let done = false
    const calls = mockApi({
      'GET /v1/me': () => (done ? { body: me() } : { status: 401, body: { detail: 'no' } }),
      'GET /v1/setup/status': { body: { needs_setup: true } },
      'POST /v1/setup': () => {
        done = true
        return { status: 201, body: me() }
      },
      'GET /v1/agents': { body: [agent()] },
    })
    renderAt('/setup')
    await fill()
    expect(await screen.findByRole('heading', { name: 'Agents' })).toBeInTheDocument()
    const post = calls.find((c) => c.path === '/v1/setup')!
    expect(post.body).toEqual({
      setup_token: 'tok-from-server-log',
      workspace_name: 'Acme',
      display_name: 'Olivia Owner',
      email: 'olivia@example.com',
      password: 'correct horse battery',
    })
    expect(JSON.stringify(post.body)).not.toContain('confirm')
  })

  it('catches a mismatched or short password before anything is sent', async () => {
    const calls = mockApi(signedOut(true))
    renderAt('/setup')
    await fill({ confirm: 'something else entirely' })
    expect(await screen.findByRole('alert')).toHaveTextContent(/do not match/i)
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('rejects a short password up front', async () => {
    const calls = mockApi(signedOut(true))
    renderAt('/setup')
    await fill({ password: 'short', confirm: 'short' })
    expect(await screen.findByRole('alert')).toHaveTextContent(/at least 10 characters/i)
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('explains a wrong setup token', async () => {
    mockApi({
      ...signedOut(true),
      'POST /v1/setup': { status: 403, body: { detail: 'Invalid setup token.' } },
    })
    renderAt('/setup')
    await fill()
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid setup token.')
  })

  it('is closed once the instance has been set up', async () => {
    mockApi(signedOut(false))
    renderAt('/setup')
    await waitFor(() => expect(window.location.pathname).toBe('/signin'))
  })
})
