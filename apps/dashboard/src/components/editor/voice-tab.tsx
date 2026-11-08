import type { AgentConfig, CatalogOut, ModelOut } from '@/api/types'
import { Field } from '@/components/field'
import type { TabProps } from '@/components/field'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import { DIRECT_PROVIDERS, supportsOwnKey } from '@/lib/direct'
import type { Connection, Kind } from '@/lib/direct'

interface Choice {
  provider: string
  model: string
  connection?: Connection
}

const idOf = (c: Choice) => `${c.provider}/${c.model}`

/** Switching model keeps the connection choice only where the new provider still supports it. */
function pick<T extends Choice>(prev: T | null | undefined, next: Choice, kind: Kind): T {
  const connection: Connection =
    prev?.connection === 'own' && supportsOwnKey(kind, next.provider) ? 'own' : 'livekit'
  return { ...prev, provider: next.provider, model: next.model, connection } as T
}

function ModelSelect({
  id,
  kind,
  label,
  options,
  value,
  onSelect,
  onConnection,
  disabled,
  error,
}: {
  id: string
  kind: Kind
  label: string
  options: ModelOut[]
  value: Choice | null | undefined
  onSelect: (c: Choice) => void
  onConnection: (c: Connection) => void
  disabled?: boolean
  error?: string
}) {
  const current = value ? idOf(value) : ''
  const items = options.map((o) => ({ value: idOf(o), label: o.label }))
  // A saved model that is not in the curated list must still be visible, never silently swapped.
  if (current && !items.some((i) => i.value === current)) items.unshift({ value: current, label: current })
  const note = options.find((o) => idOf(o) === current)?.note

  return (
    <Field label={label} htmlFor={id} hint={note} error={error}>
      <Select
        value={current}
        items={items}
        disabled={disabled}
        onValueChange={(v) => {
          if (!v) return
          const [provider, ...rest] = v.split('/')
          onSelect({ provider: provider ?? '', model: rest.join('/') })
        }}
      >
        <SelectTrigger id={id} className="w-full" aria-invalid={!!error}>
          <SelectValue placeholder="Choose a model" />
        </SelectTrigger>
        <SelectContent>
          {items.map((i) => (
            <SelectItem key={i.value} value={i.value}>
              {i.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {value && supportsOwnKey(kind, value.provider) && (
        <div className="mt-2 flex items-center gap-2 text-sm">
          <label htmlFor={`${id}-connection`} className="text-muted-foreground shrink-0">
            Connect via
          </label>
          <Select
            value={value.connection ?? 'livekit'}
            items={[
              { value: 'livekit', label: 'LiveKit' },
              { value: 'own', label: `My ${DIRECT_PROVIDERS[kind][value.provider]} key` },
            ]}
            disabled={disabled}
            onValueChange={(v) => v && onConnection(v as Connection)}
          >
            <SelectTrigger id={`${id}-connection`} size="sm" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="livekit">LiveKit</SelectItem>
              <SelectItem value="own">My {DIRECT_PROVIDERS[kind][value.provider]} key</SelectItem>
            </SelectContent>
          </Select>
        </div>
      )}
    </Field>
  )
}

export function VoiceTab({
  config,
  onChange,
  errors,
  disabled,
  catalog,
}: TabProps<AgentConfig> & { catalog: CatalogOut | undefined }) {
  const empty: CatalogOut = { stt: [], llm: [], tts: [], default_voice_id: '' }
  const cat = catalog ?? empty
  const tts = config.tts
  return (
    <div className="grid gap-6">
      <div className="grid gap-6 md:grid-cols-2">
        <ModelSelect
          id="stt-model"
          kind="stt"
          label="Speech recognition"
          options={cat.stt}
          value={config.stt}
          disabled={disabled}
          error={errors.stt}
          onSelect={(c) => onChange({ ...config, stt: pick(config.stt, c, 'stt') })}
          onConnection={(connection) =>
            config.stt && onChange({ ...config, stt: { ...config.stt, connection } })
          }
        />
        <ModelSelect
          id="llm-model"
          kind="llm"
          label="Language model"
          options={cat.llm}
          value={config.llm}
          disabled={disabled}
          error={errors.llm}
          onSelect={(c) => onChange({ ...config, llm: pick(config.llm, c, 'llm') })}
          onConnection={(connection) =>
            config.llm && onChange({ ...config, llm: { ...config.llm, connection } })
          }
        />
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <ModelSelect
          id="tts-model"
          kind="tts"
          label="Voice model"
          options={cat.tts}
          value={tts}
          disabled={disabled}
          error={errors.tts}
          onSelect={(c) => tts && onChange({ ...config, tts: pick(tts, c, 'tts') })}
          onConnection={(connection) => tts && onChange({ ...config, tts: { ...tts, connection } })}
        />
        <Field
          label="Voice ID"
          htmlFor="voice-id"
          error={errors['tts.voice_id']}
          hint="The provider's identifier for the voice."
        >
          <Input
            id="voice-id"
            value={tts?.voice_id ?? ''}
            onChange={(e) => tts && onChange({ ...config, tts: { ...tts, voice_id: e.target.value } })}
            spellCheck={false}
            disabled={disabled}
          />
        </Field>
      </div>

      <Field
        label={`Speaking speed · ${(tts?.speed ?? 1).toFixed(2)}×`}
        htmlFor="voice-speed"
        error={errors['tts.speed']}
      >
        <Slider
          id="voice-speed"
          min={0.7}
          max={1.3}
          step={0.05}
          value={[tts?.speed ?? 1]}
          disabled={disabled}
          onValueChange={(v) => {
            const n = Array.isArray(v) ? v[0] : v
            if (tts && typeof n === 'number') onChange({ ...config, tts: { ...tts, speed: n } })
          }}
        />
      </Field>
    </div>
  )
}
