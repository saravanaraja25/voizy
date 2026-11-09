import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import type { AgentConfig } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { Field } from '@/components/field'
import type { TabProps } from '@/components/field'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'

const MODES = [
  { value: 'prefetch', label: 'Look up on every turn (fastest)' },
  { value: 'tool', label: 'Let the agent decide when to look up' },
  { value: 'prompt', label: 'Put it all in the instructions (small collections)' },
]
const MODE_HINT: Record<string, string> = {
  prefetch: 'Best passages are found before the agent replies, so there is no extra model round trip.',
  tool: 'The agent calls a search tool when it needs a fact. More flexible, but adds a model round trip.',
  prompt: 'The whole collection is read at the start of each call. Works only for small collections (about 12,000 characters); larger ones fall back to looking up on every turn.',
}

export function KnowledgeTab({ config, onChange, errors, disabled }: TabProps<AgentConfig>) {
  const { client, can } = useAuth()
  // The server fills defaults, so older saved configs may not carry every field.
  const r = { enabled: false, collection: 'default', mode: 'prefetch' as const, top_k: 3, ...config.retrieval }
  const collections = useQuery({
    queryKey: ['kb', 'collections'],
    queryFn: () => client!.collections(),
    enabled: !!client && can('kb:read'),
  })
  const set = (patch: Partial<typeof r>) => onChange({ ...config, retrieval: { ...r, ...patch } })

  return (
    <div className="grid gap-6">
      <div className="flex items-start justify-between gap-4 rounded-lg border p-4">
        <div className="grid gap-1">
          <label htmlFor="kb-enabled" className="font-medium">
            Answer from the knowledge base
          </label>
          <p className="text-muted-foreground text-sm">
            The agent uses your documents for facts instead of guessing.{' '}
            <Link to="/knowledge" className="underline underline-offset-4">
              Manage documents
            </Link>
          </p>
        </div>
        <Switch id="kb-enabled" checked={r.enabled} disabled={disabled} onCheckedChange={(v) => set({ enabled: v })} aria-label="Answer from the knowledge base" />
      </div>

      {r.enabled && (
        <>
          <Field
            label="Collection"
            htmlFor="kb-collection-pick"
            error={errors['retrieval.collection']}
            hint="The set of documents this agent reads."
          >
            <Input id="kb-collection-pick" list="kb-tab-collections" value={r.collection} onChange={(e) => set({ collection: e.target.value })} disabled={disabled} maxLength={40} />
            <datalist id="kb-tab-collections">
              {(collections.data?.collections ?? []).map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
          </Field>

          <Field label="How it reaches the agent" htmlFor="kb-mode" hint={MODE_HINT[r.mode]}>
            <Select value={r.mode} items={MODES} disabled={disabled} onValueChange={(v) => v && set({ mode: v as typeof r.mode })}>
              <SelectTrigger id="kb-mode" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {MODES.map((m) => (
                  <SelectItem key={m.value} value={m.value}>
                    {m.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          {r.mode !== 'prompt' && (
            <Field label={`Passages per lookup · ${r.top_k}`} htmlFor="kb-topk" hint="More passages cover more, but make the reply slower.">
              <Slider id="kb-topk" min={1} max={10} step={1} value={[r.top_k]} disabled={disabled} onValueChange={(v) => { const n = Array.isArray(v) ? v[0] : v; if (typeof n === 'number') set({ top_k: n }) }} />
            </Field>
          )}
        </>
      )}
    </div>
  )
}
