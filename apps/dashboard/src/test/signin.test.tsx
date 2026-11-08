import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { agent, API, me, mockApi, renderAt } from './harness'

describe('sign in', () => {
  it('redirects signed-out visitors and blocks submit until a key is entered', async () => {
    mockApi({})
    renderAt('/')
    expect(await screen.findByRole('heading', { name: /sign in to voizy/i })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/signin')
    expect(screen.getByRole('button', { name: /^sign in$/i })).toBeDisabled()
  })

  it('signs in with the key, calls the API with a bearer token, and lands on agents', async () => {
    const calls = mockApi({ 'GET /v1/me': { body: me() }, 'GET /v1/agents': { body: [agent()] } })
    renderAt('/signin')
    const user = userEvent.setup()
    await user.clear(await screen.findByLabelText(/api url/i))
    await user.type(screen.getByLabelText(/api url/i), API)
    await user.type(screen.getByLabelText(/api key/i), 'vz_secret_key')
    await user.click(screen.getByRole('button', { name: /^sign in$/i }))

    expect(await screen.findByRole('heading', { name: 'Agents' })).toBeInTheDocument()
    expect(calls[0]).toMatchObject({ method: 'GET', path: '/v1/me', auth: 'Bearer vz_secret_key' })
    expect(JSON.parse(sessionStorage.getItem('voizy.session')!)).toEqual({ baseUrl: API, key: 'vz_secret_key' })
    expect(localStorage.getItem('voizy.session')).toBeNull() // never persisted beyond the tab
  })

  it('shows the server error and stores nothing when the key is rejected', async () => {
    mockApi({ 'GET /v1/me': { status: 401, body: { detail: 'invalid or missing credentials' } } })
    renderAt('/signin')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText(/api key/i), 'vz_wrong')
    await user.click(screen.getByRole('button', { name: /^sign in$/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid or missing credentials/i)
    expect(sessionStorage.getItem('voizy.session')).toBeNull()
  })

  it('rejects an insecure remote API url before sending anything', async () => {
    const calls = mockApi({})
    renderAt('/signin')
    const user = userEvent.setup()
    await user.clear(await screen.findByLabelText(/api url/i))
    await user.type(screen.getByLabelText(/api url/i), 'http://api.example.com')
    await user.type(screen.getByLabelText(/api key/i), 'vz_key')
    await user.click(screen.getByRole('button', { name: /^sign in$/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/valid API URL/i)
    expect(calls).toHaveLength(0)
  })

  it('restores a stored session and signs out on request', async () => {
    mockApi({ 'GET /v1/me': { body: me() }, 'GET /v1/agents': { body: [] } })
    sessionStorage.setItem('voizy.session', JSON.stringify({ baseUrl: API, key: 'vz_k' }))
    renderAt('/')
    expect(await screen.findByRole('heading', { name: 'Agents' })).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /account menu/i }))
    await user.click(await screen.findByRole('menuitem', { name: /sign out/i }))
    await waitFor(() => expect(window.location.pathname).toBe('/signin'))
    expect(sessionStorage.getItem('voizy.session')).toBeNull()
  })
})
