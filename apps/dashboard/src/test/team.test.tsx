import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { CSRF, me, mockApi, renderAt } from './harness'

const members = [
  {
    user_id: 'u-me',
    email: 'olivia@example.com',
    display_name: 'Olivia Owner',
    role_id: 'r-super',
    role_name: 'Superadmin',
    joined_at: '2026-11-01T10:00:00Z',
    last_login_at: '2026-11-08T09:00:00Z',
  },
  {
    user_id: 'u-bob',
    email: 'bob@example.com',
    display_name: 'Bob Builder',
    role_id: 'r-builder',
    role_name: 'Builder',
    joined_at: '2026-11-02T10:00:00Z',
    last_login_at: null,
  },
]
const roles = [
  { id: 'r-analyst', name: 'Analyst' },
  { id: 'r-builder', name: 'Builder' },
]
const base = {
  'GET /v1/me': { body: me() },
  'GET /v1/members': { body: members },
  'GET /v1/assignable-roles': { body: roles },
  'GET /v1/invites': { body: [] },
  'GET /v1/agents': { body: [] },
}

describe('team page', () => {
  it('lists members, marks you, and offers no actions on yourself', async () => {
    mockApi(base)
    renderAt('/team')
    expect(await screen.findByText('Bob Builder')).toBeInTheDocument()
    expect(screen.getByText('You')).toBeInTheDocument()
    expect(screen.getByText('Never')).toBeInTheDocument() // Bob has not signed in yet
    expect(screen.queryByRole('button', { name: /remove olivia/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /remove bob@example.com/i })).toBeInTheDocument()
    // Olivia's Superadmin role is not one she can hand out, so it is shown read-only.
    expect(screen.queryByRole('combobox', { name: /role for olivia/i })).not.toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: /role for bob@example.com/i })).toBeInTheDocument()
  })

  it('changes a role with the CSRF token and confirms it', async () => {
    const calls = mockApi({
      ...base,
      'PUT /v1/members/u-bob/role': { body: { ...members[1], role_id: 'r-analyst', role_name: 'Analyst' } },
    })
    renderAt('/team')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('combobox', { name: /role for bob@example.com/i }))
    await user.click(await screen.findByRole('option', { name: 'Analyst' }))
    expect(await screen.findByText(/bob builder is now analyst/i)).toBeInTheDocument()
    const put = calls.find((c) => c.method === 'PUT')!
    expect(put.body).toEqual({ role_id: 'r-analyst' })
    expect(put.csrf).toBe(CSRF)
  })

  it('shows the server reason when a change is refused', async () => {
    mockApi({
      ...base,
      'PUT /v1/members/u-bob/role': { status: 403, body: { detail: 'a workspace must keep at least one superadmin' } },
    })
    renderAt('/team')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('combobox', { name: /role for bob@example.com/i }))
    await user.click(await screen.findByRole('option', { name: 'Analyst' }))
    expect(await screen.findByText(/at least one superadmin/i)).toBeInTheDocument()
  })

  it('removes a member only after confirmation', async () => {
    const calls = mockApi({ ...base, 'DELETE /v1/members/u-bob': { status: 204 } })
    renderAt('/team')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /remove bob@example.com/i }))
    const dialog = await screen.findByRole('alertdialog')
    expect(within(dialog).getByText(/sessions end/i)).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    await user.click(within(dialog).getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE' && c.path === '/v1/members/u-bob')).toBe(true))
  })

  it('creates an invitation and shows the one-time link with the dashboard origin', async () => {
    const token = 'vzi_' + 'B'.repeat(43)
    const calls = mockApi({
      ...base,
      'POST /v1/invites': {
        status: 201,
        body: { id: 'i1', email: 'new@example.com', role_name: 'Analyst', expires_at: '2026-12-01T00:00:00Z', created_at: '2026-11-24T00:00:00Z', token, invite_path: `/invite/${token}` },
      },
    })
    renderAt('/team')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /invite someone/i }))
    await user.type(await screen.findByLabelText('Email'), 'New@Example.com')
    await user.click(screen.getByRole('combobox', { name: /role/i }))
    await user.click(await screen.findByRole('option', { name: 'Analyst' }))
    await user.click(screen.getByRole('button', { name: /create invitation/i }))

    const link = await screen.findByLabelText('Invitation link')
    expect(link).toHaveValue(`${window.location.origin}/invite/${token}`)
    expect(screen.getByText(/shown only now/i)).toBeInTheDocument()
    const post = calls.find((c) => c.path === '/v1/invites' && c.method === 'POST')!
    expect(post.body).toEqual({ email: 'New@Example.com', role_id: 'r-analyst' })
    expect(post.csrf).toBe(CSRF)
  })

  it('lists pending invitations and lets you withdraw one', async () => {
    const calls = mockApi({
      ...base,
      'GET /v1/invites': {
        body: [{ id: 'i1', email: 'pending@example.com', role_name: 'Analyst', expires_at: '2026-12-01T00:00:00Z', created_at: '2026-11-24T00:00:00Z' }],
      },
      'DELETE /v1/invites/i1': { status: 204 },
    })
    renderAt('/team')
    expect(await screen.findByText('pending@example.com')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: /withdraw invitation for pending@example.com/i }))
    expect(await screen.findByText(/invitation withdrawn/i)).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'DELETE' && c.path === '/v1/invites/i1')).toBe(true)
  })

  it('hides the Team nav and explains the page without the permission', async () => {
    mockApi({ 'GET /v1/me': { body: me(['agents:read']) }, 'GET /v1/agents': { body: [] } })
    renderAt('/team')
    expect(await screen.findByText(/need the “manage members” permission/i)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /^team$/i })).not.toBeInTheDocument()
  })

  it('shows the Team nav to people who can manage members', async () => {
    mockApi(base)
    renderAt('/')
    expect(await screen.findByRole('link', { name: /^team$/i })).toHaveAttribute('href', '/team')
  })
})
