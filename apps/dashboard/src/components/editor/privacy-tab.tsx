import type { AgentConfig } from '@/api/types'
import { Field } from '@/components/field'
import type { TabProps } from '@/components/field'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'

// The server fills these defaults, so an older saved config may not carry every field.
const DEFAULTS = { record_calls: false, redact_pii: true, retention_days: 30, save_transcripts: true }

function Row({ id, title, children, checked, onChecked, disabled }: {
  id: string
  title: string
  children: string
  checked: boolean
  onChecked: (v: boolean) => void
  disabled?: boolean
}) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-lg border p-4">
      <div className="grid gap-1">
        <label htmlFor={id} className="font-medium">
          {title}
        </label>
        <p className="text-muted-foreground text-sm">{children}</p>
      </div>
      <Switch id={id} checked={checked} disabled={disabled} onCheckedChange={onChecked} aria-label={title} />
    </div>
  )
}

/** What is kept from this agent's calls. Audio is never recorded, so there is no recording setting. */
export function PrivacyTab({ config, onChange, errors, disabled }: TabProps<AgentConfig>) {
  const p = { ...DEFAULTS, ...config.policy }
  const set = (patch: Partial<typeof p>) => onChange({ ...config, policy: { ...p, ...patch } })

  return (
    <div className="grid gap-6">
      <Row
        id="keep-transcripts"
        title="Keep transcripts"
        checked={p.save_transcripts}
        disabled={disabled}
        onChecked={(v) => set({ save_transcripts: v })}
      >
        When off, only call details are kept (time, length, status and response times), never what was said.
      </Row>
      <Row
        id="redact-pii"
        title="Mask personal details"
        checked={p.redact_pii}
        disabled={disabled || !p.save_transcripts}
        onChecked={(v) => set({ redact_pii: v })}
      >
        Replaces emails, card numbers, phone numbers and ID-like numbers (including ones spoken as words)
        before a transcript is saved. A safety net, not a guarantee: names and addresses are not caught.
      </Row>
      <Field
        label="Delete calls after (days)"
        htmlFor="retention-days"
        error={errors['policy.retention_days']}
        hint="0 keeps no transcript at all; call details are still kept for 30 days. Expired calls are removed automatically."
      >
        <Input
          id="retention-days"
          type="number"
          min={0}
          max={3650}
          value={p.retention_days}
          disabled={disabled}
          onChange={(e) => set({ retention_days: Number(e.target.value) })}
          className="w-40"
        />
      </Field>
      <p className="text-muted-foreground text-sm">Call audio is not recorded.</p>
    </div>
  )
}
