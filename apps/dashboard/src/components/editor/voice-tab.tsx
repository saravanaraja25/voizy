import type { AgentConfig, CatalogOut, ModelOut } from '@/api/types'
import { Field } from '@/components/field'
import type { TabProps } from '@/components/field'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'

interface Choice {
  provider: string
  model: string
}

const idOf = (c: Choice) => `${c.provider}/${c.model}`

function ModelSelect({
  id,
  label,
  options,
  value,
  onSelect,
  disabled,
  error,
}: {
  id: string
  label: string
  options: ModelOut[]
  value: Choice | null | undefined
  onSelect: (c: Choice) => void
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
          label="Speech recognition"
          options={cat.stt}
          value={config.stt}
          disabled={disabled}
          error={errors.stt}
          onSelect={(c) => onChange({ ...config, stt: c })}
        />
        <ModelSelect
          id="llm-model"
          label="Language model"
          options={cat.llm}
          value={config.llm}
          disabled={disabled}
          error={errors.llm}
          onSelect={(c) => onChange({ ...config, llm: c })}
        />
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <ModelSelect
          id="tts-model"
          label="Voice model"
          options={cat.tts}
          value={tts}
          disabled={disabled}
          error={errors.tts}
          onSelect={(c) => tts && onChange({ ...config, tts: { ...tts, ...c } })}
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
