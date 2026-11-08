import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { CSRF, me, mockApi, renderAt } from './harness'

const field = (over: Record<string, unknown>) => ({
  secret: true,
  configured: false,
  value: null,
  hint: '',
  placeholder: '',
  help: '',
  ...over,
})

const livekit = (configured: boolean) => ({
  id: 'livekit',
  label: 'LiveKit',
  description: 'Real-time audio rooms.',
  used_for: 'Test calls and the voice agent.',
  configured,
  fields: [
    field({ name: 'livekit_url', label: 'Project URL', secret: false, configured, value: configured ? 'wss://proj.livekit.cloud' : null, placeholder: 'wss://your-project.livekit.cloud' }),
    field({ name: 'livekit_api_key', label: 'API key', configured, hint: configured ? '••••sts1' : '' }),
    field({ name: 'livekit_api_secret', label: 'API secret', configured, hint: configured ? '••••0001' : '' }),
  ],
})
const twilio = {
  id: 'twilio',
  label: 'Twilio',
  description: 'Phone numbers and calls.',
  used_for: 'Calls.',
  configured: false,
  fields: [
    field({ name: 'twilio_account_sid', label: 'Account SID', secret: false }),
    field({ name: 'twilio_auth_token', label: 'Auth token' }),
  ],
}
const secret = {
  name: 'clinic_api_key',
  description: 'Clinic backend',
  allowed_hosts: ['api.clinic.example', '*.clinic.example'],
  hint: '••••6789',
  updated_at: '2026-11-08T10:00:00Z',
}
const base = {
  'GET /v1/me': { body: me() },
  'GET /v1/agents': { body: [] },
  'GET /v1/integrations': { body: [livekit(true), twilio] },
  'GET /v1/secrets': { body: [secret] },
}

describe('settings: integrations', () => {
  it('shows each integration with its status and only masked values', async () => {
    mockApi(base)
    renderAt('/settings')
    const lk = (await screen.findByText('LiveKit')).closest('[data-slot="card"]') as HTMLElement
    expect(within(lk).getByText('Connected')).toBeInTheDocument()
    expect(within(lk).getByText('wss://proj.livekit.cloud')).toBeInTheDocument() // a URL is not secret
    expect(within(lk).getByText('••••sts1')).toBeInTheDocument()
    expect(within(lk).getByText('••••0001')).toBeInTheDocument()
    const tw = screen.getByText('Twilio').closest('[data-slot="card"]') as HTMLElement
    expect(within(tw).getByText('Not connected')).toBeInTheDocument()
    expect(within(tw).queryByRole('button', { name: /test connection/i })).not.toBeInTheDocument()
  })

  it('connects an integration: secret fields are masked inputs and the save carries every value', async () => {
    const calls = mockApi({
      ...base,
      'PUT /v1/integrations/twilio': { body: { ...twilio, configured: true } },
    })
    renderAt('/settings')
    const user = userEvent.setup()
    const tw = (await screen.findByText('Twilio')).closest('[data-slot="card"]') as HTMLElement
    await user.click(within(tw).getByRole('button', { name: /connect/i }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByLabelText('Auth token')).toHaveAttribute('type', 'password')
    expect(within(dialog).getByLabelText('Account SID')).toHaveAttribute('type', 'text')
    await user.type(within(dialog).getByLabelText('Account SID'), 'AC' + 'a'.repeat(32))
    await user.type(within(dialog).getByLabelText('Auth token'), 'b'.repeat(32))
    await user.click(within(dialog).getByRole('button', { name: /^save$/i }))
    expect(await screen.findByText(/twilio saved/i)).toBeInTheDocument()
    const put = calls.find((c) => c.method === 'PUT')!
    expect(put.body).toEqual({ values: { twilio_account_sid: 'AC' + 'a'.repeat(32), twilio_auth_token: 'b'.repeat(32) } })
    expect(put.csrf).toBe(CSRF)
  })

  it('editing sends only what changed, so a saved key is never re-entered or resent', async () => {
    const calls = mockApi({ ...base, 'PUT /v1/integrations/livekit': { body: livekit(true) } })
    renderAt('/settings')
    const user = userEvent.setup()
    const lk = (await screen.findByText('LiveKit')).closest('[data-slot="card"]') as HTMLElement
    await user.click(within(lk).getByRole('button', { name: /^edit$/i }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByLabelText('API key')).toHaveValue('') // the key is not in the form
    expect(within(dialog).getByLabelText('API key')).toHaveAttribute('placeholder', '••••sts1 (saved)')
    const url = within(dialog).getByLabelText('Project URL')
    await user.clear(url)
    await user.type(url, 'wss://other.livekit.cloud')
    await user.click(within(dialog).getByRole('button', { name: /^save$/i }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    expect(calls.find((c) => c.method === 'PUT')!.body).toEqual({ values: { livekit_url: 'wss://other.livekit.cloud' } })
  })

  it('tests the connection and reports success or the provider rejecting the key', async () => {
    let ok = true
    mockApi({
      ...base,
      'POST /v1/integrations/livekit/test': () =>
        ok ? { body: { ok: true, message: 'Connected to LiveKit.' } } : { body: { ok: false, message: 'LiveKit rejected the API key or secret.' } },
    })
    renderAt('/settings')
    const user = userEvent.setup()
    const lk = (await screen.findByText('LiveKit')).closest('[data-slot="card"]') as HTMLElement
    await user.click(within(lk).getByRole('button', { name: /test connection/i }))
    expect(await within(lk).findByText('Connected to LiveKit.')).toBeInTheDocument()
    ok = false
    await user.click(within(lk).getByRole('button', { name: /test connection/i }))
    expect(await within(lk).findByRole('alert')).toHaveTextContent('LiveKit rejected the API key or secret.')
  })

  it('disconnects only after confirmation', async () => {
    const calls = mockApi({ ...base, 'DELETE /v1/integrations/livekit': { status: 204 } })
    renderAt('/settings')
    const user = userEvent.setup()
    const lk = (await screen.findByText('LiveKit')).closest('[data-slot="card"]') as HTMLElement
    await user.click(within(lk).getByRole('button', { name: /remove/i }))
    const dialog = await screen.findByRole('alertdialog')
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    await user.click(within(dialog).getByRole('button', { name: /disconnect/i }))
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE' && c.path === '/v1/integrations/livekit')).toBe(true))
  })

  it('explains how to enable secret storage when the server has no encryption key', async () => {
    mockApi({
      ...base,
      'GET /v1/integrations': { status: 503, body: { detail: 'Secret storage is not configured.' } },
    })
    renderAt('/settings')
    expect(await screen.findByText(/secret storage is not set up/i)).toBeInTheDocument()
    expect(screen.getByText('voizy-admin generate-secret-key')).toBeInTheDocument()
  })

  it('hides Settings and says why without the permission', async () => {
    mockApi({ 'GET /v1/me': { body: me(['agents:read']) }, 'GET /v1/agents': { body: [] } })
    renderAt('/settings')
    expect(await screen.findByText(/need the “manage keys” permission/i)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /^settings$/i })).not.toBeInTheDocument()
  })
})

describe('settings: tool credentials', () => {
  async function openTab() {
    const user = userEvent.setup()
    await user.click(await screen.findByRole('tab', { name: /tool credentials/i }))
    return user
  }

  it('lists credentials with their allowed hosts and a masked hint, never a value', async () => {
    mockApi(base)
    renderAt('/settings')
    await openTab()
    expect(await screen.findByText('clinic_api_key')).toBeInTheDocument()
    expect(screen.getByText('api.clinic.example')).toBeInTheDocument()
    expect(screen.getByText('*.clinic.example')).toBeInTheDocument()
    expect(screen.getByText('••••6789')).toBeInTheDocument()
  })

  it('adds a credential: needs a value and at least one host, and splits hosts sensibly', async () => {
    const calls = mockApi({ ...base, 'PUT /v1/secrets/new_key': { body: { ...secret, name: 'new_key' } } })
    renderAt('/settings')
    const user = await openTab()
    await user.click(await screen.findByRole('button', { name: /add credential/i }))
    const dialog = await screen.findByRole('dialog')
    const save = within(dialog).getByRole('button', { name: /save credential/i })
    expect(save).toBeDisabled()
    await user.type(within(dialog).getByLabelText('Name'), 'new_key')
    await user.type(within(dialog).getByLabelText('Value'), 'a-very-secret-value')
    expect(within(dialog).getByLabelText('Value')).toHaveAttribute('type', 'password')
    expect(save).toBeDisabled() // still no host
    await user.type(within(dialog).getByLabelText('Allowed hosts'), 'api.one.example, *.two.example\napi.three.example')
    await user.click(save)
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    expect(calls.find((c) => c.method === 'PUT')!.body).toEqual({
      value: 'a-very-secret-value',
      allowed_hosts: ['api.one.example', '*.two.example', 'api.three.example'],
      description: '',
    })
  })

  it('editing can change the hosts without re-entering the value', async () => {
    const calls = mockApi({ ...base, 'PUT /v1/secrets/clinic_api_key': { body: secret } })
    renderAt('/settings')
    const user = await openTab()
    await user.click(await screen.findByRole('button', { name: 'Edit clinic_api_key' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByLabelText('Name')).toHaveAttribute('readonly')
    expect(within(dialog).getByLabelText('Value')).toHaveValue('')
    expect(within(dialog).getByText(/leave blank to keep the saved value \(••••6789\)/i)).toBeInTheDocument()
    const hosts = within(dialog).getByLabelText('Allowed hosts')
    await user.clear(hosts)
    await user.type(hosts, 'only.clinic.example')
    await user.click(within(dialog).getByRole('button', { name: /save credential/i }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    const body = calls.find((c) => c.method === 'PUT')!.body as Record<string, unknown>
    expect(body.value).toBeUndefined() // keep the stored value
    expect(body.allowed_hosts).toEqual(['only.clinic.example'])
  })

  it('deletes after confirmation', async () => {
    const calls = mockApi({ ...base, 'DELETE /v1/secrets/clinic_api_key': { status: 204 } })
    renderAt('/settings')
    const user = await openTab()
    await user.click(await screen.findByRole('button', { name: 'Delete clinic_api_key' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    await user.click(within(dialog).getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true))
  })

  it('shows an empty state', async () => {
    mockApi({ ...base, 'GET /v1/secrets': { body: [] } })
    renderAt('/settings')
    await openTab()
    expect(await screen.findByText(/no credentials yet/i)).toBeInTheDocument()
  })
})
