import type { AgentConfig } from '@/api/types'
import { Field } from '@/components/field'
import type { TabProps } from '@/components/field'
import { Input } from '@/components/ui/input'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'

type Turn = NonNullable<AgentConfig['turn']>

function SliderField({
  id,
  label,
  unit,
  hint,
  value,
  min,
  max,
  step,
  onValue,
  disabled,
  error,
}: {
  id: string
  label: string
  unit: string
  hint: string
  value: number
  min: number
  max: number
  step: number
  onValue: (n: number) => void
  disabled?: boolean
  error?: string
}) {
  return (
    <Field label={`${label} · ${value}${unit}`} htmlFor={id} hint={hint} error={error}>
      <Slider
        id={id}
        min={min}
        max={max}
        step={step}
        value={[value]}
        disabled={disabled}
        onValueChange={(v) => {
          const n = Array.isArray(v) ? v[0] : v
          if (typeof n === 'number') onValue(n)
        }}
      />
    </Field>
  )
}

function SwitchRow({
  id,
  label,
  hint,
  checked,
  onChecked,
  disabled,
}: {
  id: string
  label: string
  hint: string
  checked: boolean
  onChecked: (v: boolean) => void
  disabled?: boolean
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="grid gap-1">
        <label htmlFor={id} className="text-sm leading-none font-medium">
          {label}
        </label>
        <p className="text-muted-foreground text-xs">{hint}</p>
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onChecked} disabled={disabled} />
    </div>
  )
}

export function TurnTab({ config, onChange, errors, disabled }: TabProps<AgentConfig>) {
  const turn = config.turn as Turn
  const set = (patch: Partial<Turn>) => onChange({ ...config, turn: { ...turn, ...patch } })

  return (
    <div className="grid gap-6">
      <p className="text-muted-foreground text-sm">
        These control how quickly the agent decides you have finished speaking. Faster feels more
        natural but risks interrupting people mid-thought. In our tests 300 ms split one sentence
        into two turns; 420–550 ms did not.
      </p>
      <div className="grid gap-6 md:grid-cols-2">
        <SliderField
          id="vad-silence"
          label="Silence that ends speech"
          unit=" ms"
          hint="Lower = quicker replies, more cut-offs."
          value={turn.vad_min_silence_ms}
          min={100}
          max={2000}
          step={10}
          disabled={disabled}
          error={errors['turn.vad_min_silence_ms']}
          onValue={(n) => set({ vad_min_silence_ms: n })}
        />
        <SliderField
          id="vad-threshold"
          label="Voice sensitivity"
          unit=""
          hint="Higher ignores more background noise."
          value={turn.vad_threshold}
          min={0.1}
          max={0.95}
          step={0.05}
          disabled={disabled}
          error={errors['turn.vad_threshold']}
          onValue={(n) => set({ vad_threshold: Number(n.toFixed(2)) })}
        />
        <SliderField
          id="endpoint-min"
          label="Minimum wait before replying"
          unit=" ms"
          hint="A floor on how soon the agent may answer."
          value={turn.min_endpointing_delay_ms}
          min={0}
          max={1500}
          step={50}
          disabled={disabled}
          error={errors['turn.min_endpointing_delay_ms']}
          onValue={(n) => set({ min_endpointing_delay_ms: n })}
        />
        <SliderField
          id="endpoint-max"
          label="Maximum wait when unsure"
          unit=" ms"
          hint="How long to wait if you might not be finished."
          value={turn.max_endpointing_delay_ms}
          min={200}
          max={4000}
          step={100}
          disabled={disabled}
          error={errors['turn.max_endpointing_delay_ms']}
          onValue={(n) => set({ max_endpointing_delay_ms: n })}
        />
      </div>

      <div className="grid gap-5 border-t pt-6">
        <SwitchRow
          id="allow-interruptions"
          label="Allow interruptions"
          hint="The caller can talk over the agent and it will stop."
          checked={turn.allow_interruptions}
          onChecked={(v) => set({ allow_interruptions: v })}
          disabled={disabled}
        />
        <SwitchRow
          id="preemptive"
          label="Start thinking early"
          hint="Begin generating a reply before the turn is confirmed over. Faster, occasionally wasted work."
          checked={turn.preemptive_generation}
          onChecked={(v) => set({ preemptive_generation: v })}
          disabled={disabled}
        />
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Field
          label="Words needed to interrupt"
          htmlFor="interrupt-words"
          error={errors['turn.interruption_min_words']}
          hint="Ignores short sounds like “mm-hm”."
        >
          <Input
            id="interrupt-words"
            type="number"
            min={0}
            max={10}
            value={turn.interruption_min_words}
            onChange={(e) => set({ interruption_min_words: Number(e.target.value) })}
            disabled={disabled}
          />
        </Field>
        <Field
          label="Maximum call length (seconds)"
          htmlFor="max-call"
          error={errors['turn.max_call_duration_s']}
        >
          <Input
            id="max-call"
            type="number"
            min={30}
            max={7200}
            value={turn.max_call_duration_s}
            onChange={(e) => set({ max_call_duration_s: Number(e.target.value) })}
            disabled={disabled}
          />
        </Field>
      </div>
    </div>
  )
}
