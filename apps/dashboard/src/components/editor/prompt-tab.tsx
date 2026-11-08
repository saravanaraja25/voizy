import { Plus, Trash2 } from 'lucide-react'
import type { AgentConfig } from '@/api/types'
import { Field } from '@/components/field'
import type { TabProps } from '@/components/field'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

export function PromptTab({ config, onChange, errors, disabled }: TabProps<AgentConfig>) {
  const variables = config.variables ?? []
  const languages = config.languages ?? []
  const greeting = languages[0]?.greeting ?? ''

  function setGreeting(value: string) {
    const first = languages[0] ?? { code: config.default_language }
    onChange({ ...config, languages: [{ ...first, greeting: value || null }, ...languages.slice(1)] })
  }

  return (
    <div className="grid gap-6">
      <Field
        label="Instructions"
        htmlFor="system-prompt"
        error={errors.system_prompt}
        hint={
          <>
            What the agent is, how it speaks, and what it knows. Use{' '}
            <code className="bg-muted rounded px-1">{'{{variable}}'}</code> for values below, or{' '}
            <code className="bg-muted rounded px-1">{'{{agent_name}}'}</code>,{' '}
            <code className="bg-muted rounded px-1">{'{{current_time}}'}</code>.
          </>
        }
      >
        <Textarea
          id="system-prompt"
          value={config.system_prompt}
          onChange={(e) => onChange({ ...config, system_prompt: e.target.value })}
          rows={14}
          className="min-h-80 font-mono text-sm"
          disabled={disabled}
          aria-invalid={!!errors.system_prompt}
        />
      </Field>

      <Field
        label="Greeting"
        htmlFor="greeting"
        error={errors['languages.0.greeting']}
        hint="Spoken first, exactly as written. Leave empty to let the agent greet in its own words."
      >
        <Input
          id="greeting"
          value={greeting}
          onChange={(e) => setGreeting(e.target.value)}
          maxLength={500}
          disabled={disabled}
        />
      </Field>

      <fieldset className="grid gap-3" disabled={disabled}>
        <div className="flex items-center justify-between">
          <div>
            <legend className="text-sm font-medium">Variables</legend>
            <p className="text-muted-foreground text-xs">
              Named values you can reference in the instructions. Every variable used must be
              declared here.
            </p>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              onChange({
                ...config,
                variables: [...variables, { name: `var_${variables.length + 1}`, default: '', required: false }],
              })
            }
          >
            <Plus /> Add
          </Button>
        </div>
        {errors.variables && (
          <p role="alert" className="text-destructive text-sm">
            {errors.variables}
          </p>
        )}
        {variables.length === 0 && (
          <p className="text-muted-foreground text-sm">No variables declared.</p>
        )}
        {variables.map((v, i) => (
          <div key={i} className="grid grid-cols-[1fr_1.5fr_auto] items-end gap-2">
            <Field label="Name" htmlFor={`var-name-${i}`} error={errors[`variables.${i}.name`]}>
              <Input
                id={`var-name-${i}`}
                value={v.name}
                onChange={(e) =>
                  onChange({
                    ...config,
                    variables: variables.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)),
                  })
                }
                spellCheck={false}
              />
            </Field>
            <Field label="Default value" htmlFor={`var-default-${i}`}>
              <Input
                id={`var-default-${i}`}
                value={v.default ?? ''}
                onChange={(e) =>
                  onChange({
                    ...config,
                    variables: variables.map((x, j) => (j === i ? { ...x, default: e.target.value } : x)),
                  })
                }
              />
            </Field>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={`Remove variable ${v.name}`}
              onClick={() => onChange({ ...config, variables: variables.filter((_, j) => j !== i) })}
            >
              <Trash2 />
            </Button>
          </div>
        ))}
      </fieldset>
    </div>
  )
}
