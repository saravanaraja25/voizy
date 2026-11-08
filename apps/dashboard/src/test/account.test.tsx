import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { CSRF, me, mockApi, renderAt } from './harness'

async function submit(current: string, next: string, confirm: string) {
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('Current password'), current)
  await user.type(screen.getByLabelText('New password'), next)
  await user.type(screen.getByLabelText('Confirm password'), confirm)
  await user.click(screen.getByRole('button', { name: /change password/i }))
}

describe('account page', () => {
  it('shows who you are and changes the password with the CSRF token', async () => {
    const calls = mockApi({
      'GET /v1/me': { body: me() },
      'GET /v1/agents': { body: [] },
      'POST /v1/auth/password': { body: { detail: 'password changed' } },
    })
    renderAt('/account')
    await submit('old password here', 'a much better passphrase', 'a much better passphrase')
    expect(await screen.findByText(/other sessions were signed out/i)).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toHaveValue('olivia@example.com')
    const post = calls.find((c) => c.path === '/v1/auth/password')!
    expect(post.body).toEqual({ current_password: 'old password here', new_password: 'a much better passphrase' })
    expect(post.csrf).toBe(CSRF)
    expect(screen.getByLabelText('Current password')).toHaveValue('') // cleared after success
  })

  it('does not send a mismatched new password', async () => {
    const calls = mockApi({ 'GET /v1/me': { body: me() }, 'GET /v1/agents': { body: [] } })
    renderAt('/account')
    await submit('old password here', 'a much better passphrase', 'typo typo typo typo')
    expect(await screen.findByRole('alert')).toHaveTextContent(/do not match/i)
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('shows the server message when the current password is wrong', async () => {
    mockApi({
      'GET /v1/me': { body: me() },
      'GET /v1/agents': { body: [] },
      'POST /v1/auth/password': { status: 403, body: { detail: 'Current password is incorrect.' } },
    })
    renderAt('/account')
    await submit('wrong password', 'a much better passphrase', 'a much better passphrase')
    expect(await screen.findByRole('alert')).toHaveTextContent('Current password is incorrect.')
  })
})
