import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { agent, catalog, me, mockApi, renderAt, signInStored, versionOut } from './harness'
import type { Call } from './harness'

const summary = (version: number, is_published = false) => ({
  version,
  is_published,
  published_at: null,
  created_at: '2026-11-01T10:00:00Z',
})

function routes(extra: Parameters<typeof mockApi>[0] = {}, agentOver = {}, versions = [summary(1)]) {
  return {
    'GET /v1/me': { body: me() },
    'GET /v1/agents/a1': { body: agent(agentOver) },
    'GET /v1/agents/a1/versions': { body: versions },
    'GET /v1/agents/a1/versions/1': { body: versionOut(1) },
    'GET /v1/catalog': { body: catalog },
    ...extra,
  }
}

async function openEditor() {
  signInStored()
  renderAt('/agents/a1')
  return screen.findByLabelText('Instructions')
}

const edit = (el: HTMLElement, value: string) => fireEvent.change(el, { target: { value } })

describe('agent editor', () => {
  it('loads the saved version into the form and tracks unsaved changes', async () => {
    mockApi(routes())
    const prompt = await openEditor()
    expect((prompt as HTMLTextAreaElement).value).toContain('{{company}}')
    expect(screen.getByLabelText('Greeting')).toHaveValue('Hi, thanks for calling. How can I help you today?')

    const save = screen.getByRole('button', { name: /save as new version/i })
    expect(save).toBeDisabled()
    expect(screen.getByRole('button', { name: /start call/i })).toBeEnabled()

    edit(prompt, 'You are a pirate. {{company}}')
    expect(await screen.findByText('Unsaved changes')).toBeInTheDocument()
    expect(save).toBeEnabled()
    expect(screen.getByRole('button', { name: /^publish$/i })).toBeDisabled()
    // A test call must run saved config, never half-edited state.
    expect(screen.getByRole('button', { name: /start call/i })).toBeDisabled()
    expect(screen.getByText(/save your changes as a new version to test them/i)).toBeInTheDocument()
  })

  it('saves the edit as a new version with the edited config', async () => {
    const calls = mockApi(
      routes({
        'POST /v1/agents/a1/versions': (c: Call) => ({
          status: 201,
          body: versionOut(2, (c.body as { config: ReturnType<typeof versionOut>['config'] }).config),
        }),
      }),
    )
    const prompt = await openEditor()
    edit(prompt, 'Edited prompt for {{company}}')
    await userEvent.setup().click(screen.getByRole('button', { name: /save as new version/i }))

    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/v1/agents/a1/versions')).toBe(true))
    const post = calls.find((c) => c.method === 'POST')!
    expect((post.body as { config: { system_prompt: string } }).config.system_prompt).toBe('Edited prompt for {{company}}')
    expect(await screen.findByText('Saved as version 2')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument())
  })

  it('shows server validation errors on the field and flags the tab', async () => {
    mockApi(
      routes({
        'POST /v1/agents/a1/versions': {
          status: 422,
          body: {
            detail: [
              { loc: ['body', 'config', 'system_prompt'], msg: 'prompt uses undeclared variables: region' },
              { loc: ['body', 'config', 'turn', 'vad_min_silence_ms'], msg: 'Input should be >= 100' },
            ],
          },
        },
      }),
    )
    const prompt = await openEditor()
    edit(prompt, 'Hello {{region}}')
    await userEvent.setup().click(screen.getByRole('button', { name: /save as new version/i }))

    const alert = await screen.findByText('Could not save')
    expect(alert).toBeInTheDocument()
    expect(await screen.findAllByText(/undeclared variables: region/)).not.toHaveLength(0)
    expect(screen.getByRole('tab', { name: /prompt/i })).toHaveTextContent('(has errors)')
    expect(screen.getByRole('tab', { name: /turn-taking/i })).toHaveTextContent('(has errors)')
    expect(screen.getByRole('tab', { name: /tools/i })).not.toHaveTextContent('(has errors)')
  })

  it('publishes only after confirmation', async () => {
    const calls = mockApi(
      routes({
        'POST /v1/agents/a1/versions/1/publish': { body: agent({ published_version: 1 }) },
      }),
    )
    await openEditor()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /^publish$/i }))
    const dialog = await screen.findByRole('alertdialog')
    expect(within(dialog).getByText(/publish version 1\?/i)).toBeInTheDocument()
    expect(calls.some((c) => c.path.endsWith('/publish'))).toBe(false) // not yet
    await user.click(within(dialog).getByRole('button', { name: /^publish$/i }))
    expect(await screen.findByText('Version 1 is live')).toBeInTheDocument()
    expect(calls.filter((c) => c.path.endsWith('/publish'))).toHaveLength(1)
  })

  it('does not offer publishing for the version that is already live', async () => {
    mockApi(routes({}, { published_version: 1 }, [summary(1, true)]))
    await openEditor()
    expect(await screen.findByText('Live')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^publish$/i })).toBeDisabled()
  })

  it('is read-only without edit permission', async () => {
    mockApi({ ...routes(), 'GET /v1/me': { body: me(['agents:read']) } })
    const prompt = await openEditor()
    expect(prompt).toBeDisabled()
    expect(screen.queryByRole('button', { name: /save as new version/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^publish$/i })).not.toBeInTheDocument()
    expect(await screen.findByText(/read-only access/i)).toBeInTheDocument()
    expect(screen.getByText(/don't have permission to start test calls/i)).toBeInTheDocument()
  })

  it('exposes turn-taking controls with their current values', async () => {
    mockApi(routes())
    await openEditor()
    await userEvent.setup().click(screen.getByRole('tab', { name: /turn-taking/i }))
    expect(await screen.findByText(/silence that ends speech · 550 ms/i)).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: /allow interruptions/i })).toBeChecked()
    expect(screen.getByRole('switch', { name: /start thinking early/i })).toBeChecked()
  })

  it('blocks saving while a tool schema is not valid JSON, and recovers when fixed', async () => {
    mockApi(routes())
    const prompt = await openEditor()
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: /tools/i }))
    await user.click(await screen.findByRole('button', { name: /add tool/i }))

    const schema = await screen.findByLabelText(/parameters \(json schema\)/i)
    edit(schema, '{ not json')
    expect(await screen.findByText(/json/i, { selector: '[role="alert"]' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /save as new version/i })).toBeDisabled()

    edit(schema, '{"type":"object","properties":{"date":{"type":"string"}}}')
    await waitFor(() => expect(screen.getByRole('button', { name: /save as new version/i })).toBeEnabled())
    expect(prompt).toBeInTheDocument() // panels stay mounted across tab switches
  })

  it('only allows speculative execution for GET tools', async () => {
    mockApi(routes())
    await openEditor()
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: /tools/i }))
    await user.click(await screen.findByRole('button', { name: /add tool/i }))
    const spec = () => screen.getByRole('switch', { name: /run early/i })
    expect(await screen.findByRole('switch', { name: /run early/i })).not.toHaveAttribute('aria-disabled', 'true')

    await user.click(screen.getByRole('combobox', { name: /method/i }))
    await user.click(await screen.findByRole('option', { name: 'POST' }))
    await waitFor(() => expect(spec()).toHaveAttribute('aria-disabled', 'true'))
  })
})

describe('tool editor state', () => {
  it('shows a tool-level server error on the tool card', async () => {
    mockApi(
      routes({
        'POST /v1/agents/a1/versions': {
          status: 422,
          body: { detail: [{ loc: ['body', 'config', 'tools', 0, 'http'], msg: 'Value error, http tools must use https' }] },
        },
      }),
    )
    await openEditor()
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: /tools/i }))
    await user.click(await screen.findByRole('button', { name: /add tool/i }))
    await user.click(screen.getByRole('button', { name: /save as new version/i }))
    const messages = await screen.findAllByText(/http tools must use https/)
    expect(messages.some((m) => m.getAttribute('role') === 'alert')).toBe(true)
    expect(screen.getByRole('tab', { name: /tools/i })).toHaveTextContent('(has errors)')
  })

  it('keeps an invalid schema draft and its error when switching tabs and back', async () => {
    mockApi(routes())
    await openEditor()
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: /tools/i }))
    await user.click(await screen.findByRole('button', { name: /add tool/i }))
    edit(await screen.findByLabelText(/parameters \(json schema\)/i), '{ broken')
    await user.click(screen.getByRole('tab', { name: /prompt/i }))
    await user.click(screen.getByRole('tab', { name: /tools/i }))
    expect(screen.getByLabelText(/parameters \(json schema\)/i)).toHaveValue('{ broken')
    expect(screen.getByRole('button', { name: /save as new version/i })).toBeDisabled()
  })

  it('removing the first of two tools keeps the second tool’s own edits', async () => {
    mockApi(routes())
    await openEditor()
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: /tools/i }))
    await user.click(await screen.findByRole('button', { name: /add tool/i }))
    await user.click(screen.getByRole('button', { name: /add tool/i }))
    const schemas = await screen.findAllByLabelText(/parameters \(json schema\)/i)
    edit(schemas[1]!, '{"type":"object","properties":{"second":{"type":"string"}}}')
    await user.click(screen.getByRole('button', { name: /remove tool tool_1/i }))
    const remaining = await screen.findAllByLabelText(/parameters \(json schema\)/i)
    expect(remaining).toHaveLength(1)
    expect((remaining[0] as HTMLTextAreaElement).value).toContain('"second"')
  })
})
