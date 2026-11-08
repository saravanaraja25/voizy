import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { VoiceTab } from '@/components/editor/voice-tab'
import { newAgentConfig } from '@/lib/config'
import { catalog } from './harness'

describe('voice tab connection choice', () => {
  it('offers "My … key" only for providers that support it, and saves the choice', async () => {
    const config = newAgentConfig('A', catalog)
    const onChange = vi.fn()
    render(<VoiceTab config={config} onChange={onChange} errors={{}} catalog={catalog} />)
    const user = userEvent.setup()
    const llm = config.llm?.provider ?? ''
    const supported = ['openai', 'google'].includes(llm)
    expect(screen.queryAllByText('Connect via').length).toBeGreaterThan(supported ? 0 : -1)

    await user.click(screen.getAllByRole('combobox', { name: 'Connect via' })[0]!)
    await user.click(await screen.findByRole('option', { name: /^My .* key$/ }))
    expect(onChange).toHaveBeenCalled()
    const next = onChange.mock.calls.at(-1)![0]
    const changed = [next.stt, next.llm, next.tts].filter((c) => c?.connection === 'own')
    expect(changed).toHaveLength(1)
  })
})
