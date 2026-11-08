import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { agent, CSRF, me, mockApi, renderAt, signedOut } from './harness'

async function fillAndSubmit(email = 'olivia@example.com', password = 'correct horse battery') {
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('Email'), email)
  await user.type(screen.getByLabelText('Password'), password)
  await user.click(screen.getByRole('button', { name: /^sign in$/i }))
}

describe('sign in', () => {
  it('sends signed-out visitors to the sign-in form, which needs both fields', async () => {
    mockApi(signedOut())
    renderAt('/')
    expect(await screen.findByRole('heading', { name: /sign in to voizy/i })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/signin')
    expect(screen.getByRole('button', { name: /^sign in$/i })).toBeDisabled()
  })

  it('sends a fresh instance to first-run setup instead', async () => {
    mockApi(signedOut(true))
    renderAt('/')
    expect(await screen.findByRole('heading', { name: /set up voizy/i })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/setup')
  })

  it('signs in with email and password and keeps no credential in browser storage', async () => {
    let signedIn = false
    const calls = mockApi({
      'GET /v1/me': () => (signedIn ? { body: me() } : { status: 401, body: { detail: 'no' } }),
      'GET /v1/setup/status': { body: { needs_setup: false } },
      'POST /v1/auth/login': () => {
        signedIn = true
        return { body: me() }
      },
      'GET /v1/agents': { body: [agent()] },
    })
    renderAt('/signin')
    await fillAndSubmit()

    expect(await screen.findByRole('heading', { name: 'Agents' })).toBeInTheDocument()
    const login = calls.find((c) => c.path === '/v1/auth/login')!
    expect(login.body).toEqual({ email: 'olivia@example.com', password: 'correct horse battery' })
    expect(login.credentials).toBe('include')
    // The session is an HttpOnly cookie; the page must not stash anything credential-like.
    expect(sessionStorage.length).toBe(0)
    expect(JSON.stringify({ ...localStorage })).not.toMatch(/vz_|csrf|password/i)
  })

  it('shows the server message when the credentials are wrong', async () => {
    mockApi({
      ...signedOut(),
      'POST /v1/auth/login': { status: 401, body: { detail: 'Incorrect email or password.' } },
    })
    renderAt('/signin')
    await fillAndSubmit('olivia@example.com', 'wrong password!')
    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect email or password.')
    expect(window.location.pathname).toBe('/signin')
  })

  it('tells the user when they are being rate limited', async () => {
    mockApi({
      ...signedOut(),
      'POST /v1/auth/login': { status: 429, body: { detail: 'Too many attempts. Try again later.' } },
    })
    renderAt('/signin')
    await fillAndSubmit()
    expect(await screen.findByRole('alert')).toHaveTextContent(/too many attempts/i)
  })

  it('returns you to the page you were sent away from after signing in', async () => {
    let signedIn = false
    mockApi({
      'GET /v1/me': () => (signedIn ? { body: me() } : { status: 401, body: { detail: 'no' } }),
      'GET /v1/setup/status': { body: { needs_setup: false } },
      'POST /v1/auth/login': () => {
        signedIn = true
        return { body: me() }
      },
      'GET /v1/agents': { body: [] },
    })
    renderAt('/account') // protected: bounces to sign-in, remembering where you wanted to go
    await fillAndSubmit()
    expect(await screen.findByRole('heading', { name: 'Account' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/account')
  })

  it('restores an existing session on load', async () => {
    mockApi({ 'GET /v1/me': { body: me() }, 'GET /v1/agents': { body: [] } })
    renderAt('/')
    expect(await screen.findByRole('heading', { name: 'Agents' })).toBeInTheDocument()
  })

  it('signs out through the server and returns to sign-in', async () => {
    let signedIn = true
    const calls = mockApi({
      'GET /v1/me': () => (signedIn ? { body: me() } : { status: 401, body: { detail: 'no' } }),
      'GET /v1/setup/status': { body: { needs_setup: false } },
      'GET /v1/agents': { body: [] },
      'POST /v1/auth/logout': () => {
        signedIn = false
        return { body: { detail: 'signed out' } }
      },
    })
    renderAt('/')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /account menu/i }))
    await user.click(await screen.findByRole('menuitem', { name: /sign out/i }))
    await waitFor(() => expect(window.location.pathname).toBe('/signin'))
    const logout = calls.find((c) => c.path === '/v1/auth/logout')!
    expect(logout.method).toBe('POST')
    expect(logout.csrf).toBe(CSRF)
  })

  it('sends the user back to sign-in if the server ends the session mid-use', async () => {
    mockApi({
      'GET /v1/me': { body: me() },
      'GET /v1/setup/status': { body: { needs_setup: false } },
      'GET /v1/agents': { status: 401, body: { detail: 'invalid or missing credentials' } },
    })
    renderAt('/')
    await waitFor(() => expect(window.location.pathname).toBe('/signin'))
  })
})
