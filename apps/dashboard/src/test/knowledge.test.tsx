import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '@/auth/AuthContext'
import { KnowledgeTab } from '@/components/editor/knowledge-tab'
import { newAgentConfig } from '@/lib/config'
import { titleFromFilename } from '@/pages/knowledge'
import { catalog, me, mockApi, renderAt } from './harness'

const doc = { id: 'd1', collection: 'shop', title: 'Returns policy', source_name: 'returns.md', bytes: 400, chunk_count: 3, created_at: '2026-11-08T10:00:00Z' }
const base = { 'GET /v1/me': { body: me() }, 'GET /v1/kb/documents': { body: [doc] }, 'GET /v1/agents': { body: [] } }

describe('knowledge page', () => {
  it('names a document from its filename', () => {
    expect(titleFromFilename('returns_policy-v2.md')).toBe('returns policy v2')
  })

  it('shows an empty state', async () => {
    mockApi({ ...base, 'GET /v1/kb/documents': { body: [] } })
    renderAt('/knowledge')
    expect(await screen.findByText(/no documents yet/i)).toBeInTheDocument()
  })

  it('lists documents, previews sections, and deletes only after confirmation', async () => {
    const calls = mockApi({
      ...base,
      'GET /v1/kb/documents/d1': { body: { document: doc, chunks: [{ heading: 'Returns', text: 'Within 30 days of delivery.' }] } },
      'DELETE /v1/kb/documents/d1': { status: 204 },
    })
    renderAt('/knowledge')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Returns policy' }))
    expect(await screen.findByText('Within 30 days of delivery.')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    await user.click(await screen.findByRole('button', { name: /delete returns policy/i }))
    const dialog = await screen.findByRole('alertdialog')
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    await user.click(within(dialog).getByRole('button', { name: /delete document/i }))
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE' && c.csrf)).toBe(true))
  })

  it('adds a pasted document with a valid collection', async () => {
    const calls = mockApi({ ...base, 'GET /v1/kb/documents': { body: [] }, 'POST /v1/kb/documents': { status: 201, body: doc } })
    renderAt('/knowledge')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /add document/i }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Title'), 'Returns policy')
    await user.type(within(dialog).getByLabelText('Text'), '# Returns{enter}{enter}Within 30 days.')
    const collection = within(dialog).getByLabelText('Collection')
    await user.clear(collection)
    await user.type(collection, 'Bad Name')
    expect(within(dialog).getByText(/lowercase letters/i)).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: /add to knowledge base/i })).toBeDisabled()
    await user.clear(collection)
    await user.type(collection, 'shop')
    await user.click(within(dialog).getByRole('button', { name: /add to knowledge base/i }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')!.body).toMatchObject({ title: 'Returns policy', collection: 'shop' })
  })

  it('tries a search and shows the passages an agent would get', async () => {
    mockApi({
      ...base,
      'GET /v1/kb/search': { body: [{ document_title: 'Returns policy', heading: 'Returns', text: 'Refunds in 5 days.', rank: 1 }] },
    })
    renderAt('/knowledge')
    const user = userEvent.setup()
    await screen.findByText('Returns policy')
    await user.type(screen.getByLabelText('What would a caller ask?'), 'refund time')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    expect(await screen.findByText('Refunds in 5 days.')).toBeInTheDocument()
  })

  it('hides management from people who can only read', async () => {
    mockApi({ ...base, 'GET /v1/me': { body: me(['kb:read']) } })
    renderAt('/knowledge')
    await screen.findByText('Returns policy')
    expect(screen.queryByRole('button', { name: /add document/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /delete/i })).not.toBeInTheDocument()
  })
})

function Providers({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AuthProvider>
        <MemoryRouter>{children}</MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}

describe('editor knowledge tab', () => {
  it('is off by default and reveals its settings when switched on', async () => {
    mockApi({ 'GET /v1/me': { body: me() }, 'GET /v1/kb/collections': { body: { collections: ['shop'] } } })
    const onChange = vi.fn()
    const config = newAgentConfig('A', catalog)
    const { rerender } = render(<KnowledgeTab config={config} onChange={onChange} errors={{}} />, { wrapper: Providers })
    expect(screen.queryByLabelText('Collection')).not.toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('switch', { name: /answer from the knowledge base/i }))
    expect(onChange.mock.calls.at(-1)![0].retrieval).toMatchObject({ enabled: true, collection: 'default', mode: 'prefetch' })
    rerender(<KnowledgeTab config={{ ...config, retrieval: { enabled: true, collection: 'shop', mode: 'prefetch', top_k: 3 } }} onChange={onChange} errors={{}} />)
    expect(screen.getByLabelText('Collection')).toHaveValue('shop')
  })
})
