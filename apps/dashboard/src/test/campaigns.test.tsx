import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { progress } from '@/lib/campaigns'
import { agent, me, mockApi, renderAt } from './harness'

const campaign = (over: Record<string, unknown> = {}) => ({
  id: 'k1', name: 'Spring outreach', agent_id: 'a1', agent_name: 'Front desk', from_number_id: 'n1', from_number: '+14155559999',
  status: 'draft', timezone: 'Asia/Kolkata', days: [0, 1, 2, 3, 4], window_start: '09:00', window_end: '17:00',
  max_concurrent: 2, max_attempts: 2, retry_delay_min: 60, created_at: '2026-11-08T10:00:00Z', started_at: null, completed_at: null,
  counts: { pending: 3, completed: 1 }, ...over,
})
const contact = (over: Record<string, unknown> = {}) => ({
  id: 'c1', number: '•••• 0101', name: 'Ada', timezone: null, status: 'pending', attempts: 0, next_attempt_at: null,
  last_outcome: null, last_error: '', last_call_id: null, ...over,
})
const base = {
  'GET /v1/me': { body: me() },
  'GET /v1/agents': { body: [agent({ id: 'a1', name: 'Front desk', published_version: 1 })] },
  'GET /v1/phone-numbers': { body: [{ id: 'n1', e164: '+14155559999', label: 'Main', agent_id: null, agent_name: null, created_at: '2026-11-08T10:00:00Z' }] },
}

describe('campaigns', () => {
  it('counts progress from finished statuses only', () => {
    expect(progress({ pending: 3, calling: 1, completed: 2, no_answer: 1 })).toEqual({ total: 7, done: 3 })
  })

  it('lists campaigns with status and progress, or an empty state', async () => {
    mockApi({ ...base, 'GET /v1/campaigns': { body: [campaign()] } })
    renderAt('/campaigns')
    expect(await screen.findByText('Spring outreach')).toBeInTheDocument()
    expect(screen.getByText('Draft')).toBeInTheDocument()
    expect(screen.getByLabelText('1 of 4 contacts finished')).toBeInTheDocument()
  })

  it('shows an empty state and hides New campaign without campaigns:create', async () => {
    mockApi({ ...base, 'GET /v1/me': { body: me(['campaigns:read']) }, 'GET /v1/campaigns': { body: [] } })
    renderAt('/campaigns')
    expect(await screen.findByText(/no campaigns yet/i)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /new campaign/i })).not.toBeInTheDocument()
  })

  it('manages the do-not-call list', async () => {
    const calls = mockApi({
      ...base,
      'GET /v1/campaigns': { body: [] },
      'GET /v1/dnc': { body: [{ number: '+14155550101', source: 'opt_out', note: 'asked on a call', created_at: '2026-11-08T10:00:00Z' }] },
      'POST /v1/dnc': { status: 201, body: { number: '+14155550199', source: 'manual', note: '', created_at: '2026-11-08T10:00:00Z' } },
      'DELETE /v1/dnc': { status: 204 },
    })
    renderAt('/campaigns')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('tab', { name: /do not call/i }))
    expect(await screen.findByText('Asked on a call')).toBeInTheDocument()
    await user.type(screen.getByLabelText('Number'), '+1 (415) 555-0199')
    await user.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/v1/dnc')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')!.body).toEqual({ e164: '+14155550199', note: '' })
    await user.click(screen.getByRole('button', { name: 'Remove +14155550101' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true))
    expect(calls.find((c) => c.method === 'DELETE')!.csrf).toBeTruthy()
  })

  it('previews a CSV, requires consent, and creates a draft', async () => {
    const calls = mockApi({
      ...base,
      'POST /v1/campaigns/preview-csv': { body: { accepted: 2, rejected: [[4, 'duplicate number']], ignored_columns: ['coupon'], sample: [{ number: '•••• 0101', name: 'Ada' }] } },
      'POST /v1/campaigns': { status: 201, body: { campaign: campaign(), import_report: { added: 2, already_in_campaign: 0, rejected: [], ignored_columns: [] } } },
      'GET /v1/campaigns/k1': { body: campaign() },
      'GET /v1/campaigns/k1/contacts': { body: { items: [contact()], total: 1 } },
    })
    renderAt('/campaigns/new')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Name'), 'Spring outreach')
    await user.click(screen.getByRole('combobox', { name: 'Agent' }))
    await user.click(await screen.findByRole('option', { name: 'Front desk' }))
    await user.click(screen.getByRole('combobox', { name: 'Call from' }))
    await user.click(await screen.findByRole('option', { name: /\+14155559999/ }))
    await user.click(screen.getByLabelText('…or paste it'))
    await user.paste('name,phone\nAda,+14155550101\n')
    await user.click(screen.getByRole('button', { name: /check the list/i }))
    expect(await screen.findByText('2 people will be called')).toBeInTheDocument()
    expect(screen.getByText(/line 4 \(duplicate number\)/)).toBeInTheDocument()
    expect(screen.getByText(/columns the agent does not use: coupon/i)).toBeInTheDocument()

    const create = screen.getByRole('button', { name: 'Create campaign' })
    expect(create).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: /agreed to be contacted/i }))
    expect(create).toBeEnabled()
    await user.click(create)
    await waitFor(() => expect(calls.some((c) => c.path === '/v1/campaigns' && c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.path === '/v1/campaigns' && c.method === 'POST')!.body).toMatchObject({
      name: 'Spring outreach', agent_id: 'a1', from_number_id: 'n1', days: [0, 1, 2, 3, 4],
      window_start: '09:00', window_end: '17:00', consent_confirmed: true,
    })
    expect(await screen.findByRole('heading', { name: /spring outreach/i })).toBeInTheDocument()
  })

  it('shows progress and contacts, starts a draft, and confirms before cancelling', async () => {
    let status = 'draft'
    const calls = mockApi({
      ...base,
      'GET /v1/campaigns/k1': () => ({ body: campaign({ status }) }),
      'GET /v1/campaigns/k1/contacts': { body: { items: [contact(), contact({ id: 'c2', name: 'Bob', number: '•••• 0102', status: 'no_answer', attempts: 1, last_call_id: 'call-9', last_error: 'call did not start' })], total: 2 } },
      'POST /v1/campaigns/k1/start': () => { status = 'running'; return { body: campaign({ status }) } },
      'POST /v1/campaigns/k1/cancel': () => { status = 'cancelled'; return { body: campaign({ status }) } },
    })
    renderAt('/campaigns/k1')
    const user = userEvent.setup()
    expect(await screen.findByText('Ada')).toBeInTheDocument()
    expect(screen.getByText('•••• 0101')).toBeInTheDocument()
    expect(screen.getByText('call did not start')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View' })).toHaveAttribute('href', '/calls/call-9')
    await user.click(screen.getByRole('button', { name: /start/i }))
    await waitFor(() => expect(calls.some((c) => c.path === '/v1/campaigns/k1/start')).toBe(true))
    await user.click(await screen.findByRole('button', { name: /cancel campaign/i }))
    const dialog = await screen.findByRole('alertdialog')
    expect(calls.some((c) => c.path.endsWith('/cancel'))).toBe(false)
    await user.click(within(dialog).getByRole('button', { name: 'Cancel campaign' }))
    await waitFor(() => expect(calls.some((c) => c.path.endsWith('/cancel') && c.csrf)).toBe(true))
  })

  it('filters contacts by status', async () => {
    const calls = mockApi({
      ...base,
      'GET /v1/campaigns/k1': { body: campaign({ status: 'paused' }) },
      'GET /v1/campaigns/k1/contacts': { body: { items: [], total: 0 } },
    })
    renderAt('/campaigns/k1')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /no answer/i }))
    await waitFor(() => expect(calls.some((c) => c.path.endsWith('/contacts') && JSON.stringify(c).length > 0)).toBe(true))
    expect(await screen.findByText(/nobody has this status/i)).toBeInTheDocument()
  })
})
