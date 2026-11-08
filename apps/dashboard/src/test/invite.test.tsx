import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { agent, me, mockApi, renderAt, signedOut } from './harness'

const TOKEN = 'vzi_' + 'A'.repeat(43)
const preview = {
  workspace_name: 'Acme',
  email: 'new@example.com',
  role_name: 'Builder',
  expires_at: '2026-12-01T00:00:00Z',
}

describe('accepting an invitation', () => {
  it('shows who invited you, locks the email, and creates the account', async () => {
    let joined = false
    const calls = mockApi({
      ...signedOut(),
      'GET /v1/me': () => (joined ? { body: me() } : { status: 401, body: { detail: 'no' } }),
      [`GET /v1/invites/${TOKEN}`]: { body: preview },
      [`POST /v1/invites/${TOKEN}/accept`]: () => {
        joined = true
        return { status: 201, body: me() }
      },
      'GET /v1/agents': { body: [agent()] },
    })
    renderAt(`/invite/${TOKEN}`)
    expect(await screen.findByRole('heading', { name: /join acme/i })).toBeInTheDocument()
    expect(screen.getByText(/invited as builder/i)).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toHaveAttribute('readonly')
    expect(screen.getByLabelText('Email')).toHaveValue('new@example.com')

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Your name'), 'Newbie')
    await user.type(screen.getByLabelText('Password'), 'correct horse battery')
    await user.type(screen.getByLabelText('Confirm password'), 'correct horse battery')
    await user.click(screen.getByRole('button', { name: /create account/i }))

    expect(await screen.findByRole('heading', { name: 'Agents' })).toBeInTheDocument()
    const accept = calls.find((c) => c.path.endsWith('/accept'))!
    expect(accept.body).toEqual({ display_name: 'Newbie', password: 'correct horse battery' })
  })

  it('explains an invalid, used or expired link without leaking why', async () => {
    mockApi({
      ...signedOut(),
      [`GET /v1/invites/${TOKEN}`]: { status: 404, body: { detail: 'not found' } },
    })
    renderAt(`/invite/${TOKEN}`)
    expect(await screen.findByRole('heading', { name: /invitation not valid/i })).toBeInTheDocument()
    expect(screen.getByText(/expired, was already used, or was withdrawn/i)).toBeInTheDocument()
  })

  it('does not send a mismatched password', async () => {
    const calls = mockApi({ ...signedOut(), [`GET /v1/invites/${TOKEN}`]: { body: preview } })
    renderAt(`/invite/${TOKEN}`)
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Your name'), 'N')
    await user.type(screen.getByLabelText('Password'), 'correct horse battery')
    await user.type(screen.getByLabelText('Confirm password'), 'different different')
    await user.click(screen.getByRole('button', { name: /create account/i }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/do not match/i))
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })
})
