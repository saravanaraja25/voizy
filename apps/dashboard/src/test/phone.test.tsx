import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { normalizeNumber } from '@/pages/phone'
import { agent, me, mockApi, renderAt } from './harness'

const live = agent({ id: 'a1', name: 'Front desk', published_version: 1 })
const draft = agent({ id: 'a2', name: 'Draft bot', published_version: null })
const number = {
  id: 'n1',
  e164: '+14155550134',
  label: 'Main line',
  agent_id: 'a1',
  agent_name: 'Front desk',
  created_at: '2026-11-08T10:00:00Z',
}
const base = {
  'GET /v1/me': { body: me() },
  'GET /v1/agents': { body: [live, draft] },
}

describe('phone numbers', () => {
  it('normalises how people type numbers', () => {
    expect(normalizeNumber('+1 (415) 555-0134')).toBe('+14155550134')
    expect(normalizeNumber(' +44 20 7946 0958 ')).toBe('+442079460958')
    expect(normalizeNumber('415 555 0134')).toBe('4155550134') // no country code: the form rejects it
  })

  it('shows an empty state pointing to Settings', async () => {
    mockApi({ ...base, 'GET /v1/phone-numbers': { body: [] } })
    renderAt('/phone')
    expect(await screen.findByText(/no numbers connected yet/i)).toBeInTheDocument()
    const card = screen.getByText(/no numbers connected yet/i).closest('div')!
    expect(within(card).getByRole('link', { name: 'Settings' })).toHaveAttribute('href', '/settings')
  })

  it('lists numbers and hides management from people without numbers:manage', async () => {
    mockApi({
      ...base,
      'GET /v1/me': { body: me(['numbers:read', 'agents:read']) },
      'GET /v1/phone-numbers': { body: [number] },
    })
    renderAt('/phone')
    expect(await screen.findByText('+14155550134')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /connect a number/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /disconnect/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /call someone/i })).not.toBeInTheDocument()
  })

  it('connects a number only with a valid country-code number, sending E.164', async () => {
    const calls = mockApi({
      ...base,
      'GET /v1/phone-numbers': { body: [] },
      'POST /v1/phone-numbers': { status: 201, body: number },
    })
    renderAt('/phone')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /connect a number/i }))
    const dialog = await screen.findByRole('dialog')
    const submit = within(dialog).getByRole('button', { name: /connect number/i })
    const field = within(dialog).getByLabelText('Phone number')
    await user.type(field, '415 555 0134')
    expect(within(dialog).getByText(/with its country code/i)).toBeInTheDocument()
    expect(submit).toBeDisabled()
    await user.clear(field)
    await user.type(field, '+1 (415) 555-0134')
    await user.click(submit)
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    const post = calls.find((c) => c.method === 'POST')!
    expect(post.body).toEqual({ e164: '+14155550134', label: '', agent_id: null })
    expect(post.csrf).toBeTruthy()
  })

  it('only offers published agents', async () => {
    mockApi({ ...base, 'GET /v1/phone-numbers': { body: [] } })
    renderAt('/phone')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /connect a number/i }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('combobox', { name: /agent that answers/i }))
    expect(await screen.findByRole('option', { name: 'Front desk' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Draft bot' })).not.toBeInTheDocument()
  })

  it('disconnects only after confirmation', async () => {
    const calls = mockApi({
      ...base,
      'GET /v1/phone-numbers': { body: [number] },
      'DELETE /v1/phone-numbers/n1': { status: 204 },
    })
    renderAt('/phone')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /disconnect \+14155550134/i }))
    const dialog = await screen.findByRole('alertdialog')
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    await user.click(within(dialog).getByRole('button', { name: 'Disconnect' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true))
  })

  it('places an outbound call only with consent', async () => {
    const calls = mockApi({
      ...base,
      'GET /v1/phone-numbers': { body: [number] },
      'POST /v1/calls/outbound': { status: 202, body: { room: 'out-1' } },
    })
    renderAt('/phone')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /call someone from \+14155550134/i }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Call this number'), '+14155550199')
    const start = within(dialog).getByRole('button', { name: /start call/i })
    expect(start).toBeDisabled()
    await user.click(within(dialog).getByRole('checkbox', { name: /permission to call/i }))
    expect(start).toBeEnabled()
    await user.click(start)
    await waitFor(() => expect(calls.some((c) => c.path === '/v1/calls/outbound')).toBe(true))
    expect(calls.find((c) => c.path === '/v1/calls/outbound')!.body).toEqual({
      from_number_id: 'n1',
      agent_id: 'a1',
      to: '+14155550199',
      consent_confirmed: true,
    })
  })
})
