import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { agent, me, mockApi, renderAt } from './harness'

const call = (over: Record<string, unknown> = {}) => ({
  id: 'c1',
  agent_id: 'a1',
  agent_name: 'Front desk',
  agent_version: 2,
  source: 'test',
  status: 'completed',
  started_at: '2026-11-08T10:00:00Z',
  ended_at: '2026-11-08T10:01:05Z',
  duration_s: 65,
  end_reason: 'ended',
  turn_count: 2,
  latency_p50_ms: 640,
  transcript_stored: true,
  ...over,
})
const summary = { days: 7, total: 4, completed: 3, failed: 1, avg_duration_s: 40, median_latency_ms: 700 }
const base = {
  'GET /v1/me': { body: me() },
  'GET /v1/agents': { body: [agent()] },
  'GET /v1/calls/summary': { body: summary },
}
const detail = (extra: Record<string, unknown> = {}) => ({
  call: call(),
  transcript_visible: true,
  turns: [
    { seq: 0, role: 'user', text: 'Hi, I need an appointment', tool_name: null, tool_ok: null, tool_ms: null, latency: null, at: '2026-11-08T10:00:02Z' },
    { seq: 1, role: 'tool', text: '', tool_name: 'check_slots', tool_ok: true, tool_ms: 120, latency: null, at: '2026-11-08T10:00:03Z' },
    { seq: 2, role: 'agent', text: 'Sure, what day?', tool_name: null, tool_ok: null, tool_ms: null, latency: { e2e: 640 }, at: '2026-11-08T10:00:04Z' },
  ],
  ...extra,
})

describe('calls', () => {
  it('lists calls with summary figures and pages with Load more', async () => {
    const calls = mockApi({
      ...base,
      'GET /v1/calls': (c) =>
        c.path === '/v1/calls' && !JSON.stringify(c).includes('cursor')
          ? { body: { items: [call()], next_cursor: 'abc' } }
          : { body: { items: [], next_cursor: null } },
    })
    renderAt('/calls')
    expect(await screen.findByText('Front desk')).toBeInTheDocument()
    expect(screen.getByText('1m 05s')).toBeInTheDocument()
    expect(screen.getByText('640 ms')).toBeInTheDocument()
    expect(await screen.findByText('700 ms')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: /load more/i }))
    await waitFor(() => expect(calls.some((c) => c.path === '/v1/calls' && c.method === 'GET')).toBe(true))
  })

  it('shows an empty state', async () => {
    mockApi({ ...base, 'GET /v1/calls': { body: { items: [], next_cursor: null } } })
    renderAt('/calls')
    expect(await screen.findByText(/no calls yet/i)).toBeInTheDocument()
  })

  it('hides the Calls page from people without calls:read', async () => {
    mockApi({ ...base, 'GET /v1/me': { body: me(['agents:read']) } })
    renderAt('/')
    await screen.findByRole('heading', { name: 'Agents' })
    expect(screen.queryByRole('link', { name: 'Calls' })).not.toBeInTheDocument()
  })

  it('shows the transcript, tool use and latency, and deletes after confirming', async () => {
    const calls = mockApi({
      ...base,
      'GET /v1/calls': { body: { items: [], next_cursor: null } },
      'GET /v1/calls/c1': { body: detail() },
      'DELETE /v1/calls/c1': { status: 204 },
    })
    renderAt('/calls/c1')
    expect(await screen.findByText('Hi, I need an appointment')).toBeInTheDocument()
    expect(screen.getByText('check_slots')).toBeInTheDocument()
    expect(screen.getByText('Sure, what day?')).toBeInTheDocument()
    expect(screen.getByLabelText(/response time per agent turn/i)).toBeInTheDocument()

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /delete/i }))
    const dialog = await screen.findByRole('alertdialog')
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    await user.click(within(dialog).getByRole('button', { name: /delete call/i }))
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE' && c.path === '/v1/calls/c1')).toBe(true))
    expect(calls.find((c) => c.method === 'DELETE')?.csrf).toBeTruthy()
  })

  it('explains when the transcript is hidden or was never kept', async () => {
    mockApi({ ...base, 'GET /v1/calls/c1': { body: detail({ transcript_visible: false, turns: [] }) } })
    renderAt('/calls/c1')
    expect(await screen.findByText(/don’t have permission to view transcripts/i)).toBeInTheDocument()
  })

  it('says so when the agent keeps no transcripts', async () => {
    mockApi({
      ...base,
      'GET /v1/calls/c1': { body: detail({ call: call({ transcript_stored: false }), turns: [] }) },
    })
    renderAt('/calls/c1')
    expect(await screen.findByText(/doesn’t keep transcripts/i)).toBeInTheDocument()
  })
})
