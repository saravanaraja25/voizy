import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { PrivacyTab } from '@/components/editor/privacy-tab'
import { newAgentConfig } from '@/lib/config'
import { catalog } from './harness'

const base = newAgentConfig('A', catalog)

describe('privacy tab', () => {
  it('shows the defaults when the config has no policy and offers no recording control', () => {
    render(<PrivacyTab config={base} onChange={vi.fn()} errors={{}} />)
    expect(screen.getByRole('switch', { name: 'Keep transcripts' })).toBeChecked()
    expect(screen.getByRole('switch', { name: 'Mask personal details' })).toBeChecked()
    expect(screen.getByLabelText('Delete calls after (days)')).toHaveValue(30)
    expect(screen.getByText(/audio is not recorded/i)).toBeInTheDocument()
    expect(screen.queryByText(/record calls|disclosure/i)).not.toBeInTheDocument()
  })

  it('writes changes into policy and never turns recording on', async () => {
    const onChange = vi.fn()
    render(<PrivacyTab config={base} onChange={onChange} errors={{}} />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('switch', { name: 'Keep transcripts' }))
    expect(onChange.mock.calls.at(-1)![0].policy).toEqual({ record_calls: false, redact_pii: true, retention_days: 30, save_transcripts: false })
    fireEvent.change(screen.getByLabelText('Delete calls after (days)'), { target: { value: '7' } })
    expect(onChange.mock.calls.at(-1)![0].policy.retention_days).toBe(7)
  })

  it('keeps an existing policy intact and disables masking when nothing is kept', () => {
    const config = { ...base, policy: { record_calls: false, redact_pii: false, retention_days: 90, save_transcripts: false } }
    render(<PrivacyTab config={config} onChange={vi.fn()} errors={{}} />)
    expect(screen.getByLabelText('Delete calls after (days)')).toHaveValue(90)
    expect(screen.getByRole('switch', { name: 'Mask personal details' })).toHaveAttribute('aria-disabled', 'true')
  })

  it('shows a server validation error next to the field', () => {
    render(<PrivacyTab config={base} onChange={vi.fn()} errors={{ 'policy.retention_days': 'Must be at most 3650' }} />)
    expect(screen.getByText('Must be at most 3650')).toBeInTheDocument()
  })
})
