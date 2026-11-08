import { Plus, Trash2, Wrench } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import type { AgentConfig, HttpAuth, HttpTool } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { Field } from '@/components/field'
import type { TabProps } from '@/components/field'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { newHttpTool, parseSchemaText } from '@/lib/config'

type Tool = NonNullable<AgentConfig['tools']>[number]
const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((m) => ({ value: m, label: m }))
const FILLER_MODES = [
  { value: 'auto', label: 'Automatic phrases' },
  { value: 'custom', label: 'My own phrases' },
  { value: 'none', label: 'Stay silent' },
]

let nextId = 0
const newId = () => `t${++nextId}`

const AUTH_KINDS = [
  { value: 'none', label: 'None' },
  { value: 'bearer', label: 'Bearer token' },
  { value: 'header', label: 'API key in a header' },
  { value: 'basic', label: 'Basic (user:password)' },
]

/** How the tool authenticates. It names a stored credential; the value never appears here. */
function AuthSection({
  tool,
  index,
  errors,
  disabled,
  secretNames,
  onChange,
}: {
  tool: HttpTool
  index: number
  errors: Record<string, string>
  disabled?: boolean
  secretNames: string[] | null
  onChange: (t: HttpTool) => void
}) {
  const p = `tool-${index}`
  const auth = tool.auth ?? null
  const kind = auth?.kind ?? 'none'
  const error = errors[`tools.${index}.auth`] ?? errors[`tools.${index}.auth.secret`]
  const setAuth = (next: HttpAuth | null) => onChange({ ...tool, auth: next })
  const secretItems = (secretNames ?? []).map((n) => ({ value: n, label: n }))
  const known = !auth || secretItems.some((i) => i.value === auth.secret) || !auth.secret

  return (
    <div className="grid gap-4 border-t pt-5">
      <Field
        label="Authentication"
        htmlFor={`${p}-auth`}
        hint="Credentials are saved in Settings and sent only to the hosts you allow there."
      >
        <Select
          value={kind}
          items={AUTH_KINDS}
          disabled={disabled}
          onValueChange={(v) => {
            if (!v || v === 'none') return setAuth(null)
            setAuth({
              kind: v as HttpAuth['kind'],
              secret: auth?.secret ?? '',
              header_name: v === 'header' ? (auth?.header_name ?? 'X-Api-Key') : null,
            })
          }}
        >
          <SelectTrigger id={`${p}-auth`} className="w-full md:w-72">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {AUTH_KINDS.map((k) => (
              <SelectItem key={k.value} value={k.value}>
                {k.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      {auth && (
        <div className="grid gap-4 md:grid-cols-2">
          <Field
            label="Credential"
            htmlFor={`${p}-secret`}
            error={error}
            hint={
              secretNames && secretNames.length === 0
                ? 'No credentials saved yet. Add one in Settings → Tool credentials.'
                : undefined
            }
          >
            {secretNames ? (
              <Select
                value={auth.secret}
                items={secretItems}
                disabled={disabled}
                onValueChange={(v) => v && setAuth({ ...auth, secret: v })}
              >
                <SelectTrigger id={`${p}-secret`} className="w-full">
                  <SelectValue placeholder="Choose a credential" />
                </SelectTrigger>
                <SelectContent>
                  {secretItems.map((i) => (
                    <SelectItem key={i.value} value={i.value}>
                      {i.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <Input
                id={`${p}-secret`}
                value={auth.secret}
                placeholder="credential_name"
                spellCheck={false}
                disabled={disabled}
                onChange={(e) => setAuth({ ...auth, secret: e.target.value })}
              />
            )}
            {!known && (
              <p className="text-destructive text-xs" role="alert">
                “{auth.secret}” is not a saved credential.
              </p>
            )}
          </Field>
          {kind === 'header' && (
            <Field label="Header name" htmlFor={`${p}-header`} error={errors[`tools.${index}.auth.header_name`]}>
              <Input
                id={`${p}-header`}
                value={auth.header_name ?? ''}
                spellCheck={false}
                disabled={disabled}
                onChange={(e) => setAuth({ ...auth, header_name: e.target.value })}
              />
            </Field>
          )}
        </div>
      )}
    </div>
  )
}

const isHttp = (t: Tool): t is HttpTool => t.kind === 'http'

function SchemaEditor({
  id,
  value,
  disabled,
  onValid,
  onValidity,
  error,
}: {
  id: string
  value: Record<string, unknown>
  disabled?: boolean
  onValid: (v: Record<string, unknown>) => void
  onValidity: (valid: boolean) => void
  error?: string
}) {
  const [text, setText] = useState(() => JSON.stringify(value, null, 2))
  const [parseError, setParseError] = useState<string | null>(null)

  return (
    <Field
      label="Parameters (JSON schema)"
      htmlFor={id}
      error={parseError ?? error}
      hint="What the model must provide when it calls this tool. Must be an object schema."
    >
      <Textarea
        id={id}
        value={text}
        rows={8}
        spellCheck={false}
        disabled={disabled}
        className="font-mono text-xs"
        aria-invalid={!!parseError}
        onChange={(e) => {
          setText(e.target.value)
          const r = parseSchemaText(e.target.value)
          if (r.ok) {
            setParseError(null)
            onValidity(true)
            onValid(r.value)
          } else {
            setParseError(r.error)
            onValidity(false)
          }
        }}
      />
    </Field>
  )
}

function ToolCard({
  tool,
  index,
  errors,
  disabled,
  onChange,
  onRemove,
  onValidity,
  secretNames,
}: {
  tool: HttpTool
  index: number
  errors: Record<string, string>
  disabled?: boolean
  secretNames: string[] | null
  onChange: (t: HttpTool) => void
  onRemove: () => void
  onValidity: (valid: boolean) => void
}) {
  const e = (field: string) => errors[`tools.${index}.${field}`]
  const filler = tool.filler ?? newHttpTool([]).filler!
  const p = `tool-${index}`

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Wrench className="size-4" />
          <span className="font-mono">{tool.name || 'unnamed'}</span>
          <Badge variant="secondary">HTTP</Badge>
        </CardTitle>
        <CardAction>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={`Remove tool ${tool.name}`}
            disabled={disabled}
            onClick={onRemove}
          >
            <Trash2 />
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="grid gap-5">
        {errors[`tools.${index}`] && (
          <p role="alert" className="text-destructive text-sm">
            {errors[`tools.${index}`]}
          </p>
        )}
        <div className="grid gap-4 md:grid-cols-[1fr_8rem]">
          <Field label="Name" htmlFor={`${p}-name`} error={e('name')} hint="snake_case; the model calls it by this name.">
            <Input
              id={`${p}-name`}
              value={tool.name}
              spellCheck={false}
              disabled={disabled}
              onChange={(ev) => onChange({ ...tool, name: ev.target.value })}
            />
          </Field>
          <Field label="Method" htmlFor={`${p}-method`} error={e('method')}>
            <Select
              value={tool.method}
              items={METHODS}
              disabled={disabled}
              onValueChange={(v) => {
                if (!v) return
                const method = v as HttpTool['method']
                onChange({ ...tool, method, speculative: method === 'GET' ? tool.speculative : false })
              }}
            >
              <SelectTrigger id={`${p}-method`} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {METHODS.map((m) => (
                  <SelectItem key={m.value} value={m.value}>
                    {m.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        </div>

        <Field label="URL" htmlFor={`${p}-url`} error={e('url')} hint="https only. Calls to private networks are blocked.">
          <Input
            id={`${p}-url`}
            value={tool.url}
            spellCheck={false}
            disabled={disabled}
            onChange={(ev) => onChange({ ...tool, url: ev.target.value })}
          />
        </Field>

        <AuthSection
          tool={tool}
          index={index}
          errors={errors}
          disabled={disabled}
          secretNames={secretNames}
          onChange={onChange}
        />

        <Field
          label="When should the agent use it?"
          htmlFor={`${p}-desc`}
          error={e('description')}
          hint="Plain-language description the model reads to decide when to call it."
        >
          <Textarea
            id={`${p}-desc`}
            value={tool.description}
            rows={2}
            disabled={disabled}
            onChange={(ev) => onChange({ ...tool, description: ev.target.value })}
          />
        </Field>

        <SchemaEditor
          id={`${p}-schema`}
          value={(tool.parameters_schema ?? { type: 'object' }) as Record<string, unknown>}
          disabled={disabled}
          error={e('parameters_schema')}
          onValid={(v) => onChange({ ...tool, parameters_schema: v })}
          onValidity={onValidity}
        />

        <div className="grid gap-4 border-t pt-5 md:grid-cols-3">
          <Field label="Filler while waiting" htmlFor={`${p}-filler`} error={e('filler.mode')}>
            <Select
              value={filler.mode}
              items={FILLER_MODES}
              disabled={disabled}
              onValueChange={(v) => v && onChange({ ...tool, filler: { ...filler, mode: v as typeof filler.mode, phrases: v === 'custom' ? (filler.phrases?.length ? filler.phrases : ['One moment.']) : [] } })}
            >
              <SelectTrigger id={`${p}-filler`} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {FILLER_MODES.map((m) => (
                  <SelectItem key={m.value} value={m.value}>
                    {m.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Speak after (ms)" htmlFor={`${p}-delay`} error={e('filler.delay_ms')} hint="Quick lookups stay silent.">
            <Input
              id={`${p}-delay`}
              type="number"
              min={0}
              max={3000}
              value={filler.delay_ms}
              disabled={disabled || filler.mode === 'none'}
              onChange={(ev) => onChange({ ...tool, filler: { ...filler, delay_ms: Number(ev.target.value) } })}
            />
          </Field>
          <Field label="Timeout (seconds)" htmlFor={`${p}-timeout`} error={e('timeout_s')}>
            <Input
              id={`${p}-timeout`}
              type="number"
              min={1}
              max={15}
              value={tool.timeout_s}
              disabled={disabled}
              onChange={(ev) => onChange({ ...tool, timeout_s: Number(ev.target.value) })}
            />
          </Field>
        </div>

        {filler.mode === 'custom' && (
          <Field label="Filler phrases" htmlFor={`${p}-phrases`} error={e('filler')} hint="One per line, up to 5. They rotate so the agent doesn't repeat itself.">
            <Textarea
              id={`${p}-phrases`}
              rows={3}
              disabled={disabled}
              value={(filler.phrases ?? []).join('\n')}
              onChange={(ev) =>
                onChange({
                  ...tool,
                  filler: { ...filler, phrases: ev.target.value.split('\n').filter((l) => l.trim() !== '').slice(0, 5) },
                })
              }
            />
          </Field>
        )}

        <Field
          label="If it fails, tell the caller"
          htmlFor={`${p}-failure`}
          error={e('filler.failure_phrase')}
        >
          <Input
            id={`${p}-failure`}
            value={filler.failure_phrase}
            maxLength={200}
            disabled={disabled}
            onChange={(ev) => onChange({ ...tool, filler: { ...filler, failure_phrase: ev.target.value } })}
          />
        </Field>

        <div className="flex items-start justify-between gap-4">
          <div className="grid gap-1">
            <label htmlFor={`${p}-spec`} className="text-sm leading-none font-medium">
              Run early (speculative)
            </label>
            <p className="text-muted-foreground text-xs">
              Start the lookup before the caller finishes. Only for read-only GET tools.
            </p>
          </div>
          <Switch
            id={`${p}-spec`}
            checked={tool.speculative}
            disabled={disabled || tool.method !== 'GET'}
            onCheckedChange={(v) => onChange({ ...tool, speculative: v })}
          />
        </div>
      </CardContent>
    </Card>
  )
}

export function ToolsTab({
  config,
  onChange,
  errors,
  disabled,
  onValidity,
}: TabProps<AgentConfig> & { onValidity: (key: string, valid: boolean) => void }) {
  const { client, can } = useAuth()
  const canList = can('provider_keys:manage')
  const secrets = useQuery({
    queryKey: ['secrets'],
    queryFn: () => client.toolSecrets(),
    enabled: canList,
    retry: false,
  })
  // null = the user cannot list credentials (or storage is unavailable): they type the name.
  const secretNames = canList && secrets.data ? secrets.data.map((x) => x.name) : null
  const tools = config.tools ?? []
  const names = tools.map((t) => t.name)
  // Stable per-tool identity: local editor state must follow the tool, not its array position.
  // Tools only change through this tab, and a different version remounts the whole editor.
  const [ids, setIds] = useState<string[]>(() => tools.map(newId))
  const update = (i: number, t: Tool) => onChange({ ...config, tools: tools.map((x, j) => (j === i ? t : x)) })

  return (
    <div className="grid gap-4">
      <div className="flex items-start justify-between gap-4">
        <p className="text-muted-foreground max-w-prose text-sm">
          Tools let the agent look things up or act during a call. It can only claim to do what its
          tools allow. Slow tools play a short filler phrase so there is never dead air.
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          onClick={() => {
            setIds((prev) => [...prev, newId()])
            onChange({ ...config, tools: [...tools, newHttpTool(names)] })
          }}
        >
          <Plus /> Add tool
        </Button>
      </div>

      {tools.length === 0 && (
        <Card className="border-dashed">
          <CardContent className="text-muted-foreground py-10 text-center text-sm">
            No tools yet. Without any, the agent can only talk.
          </CardContent>
        </Card>
      )}

      {tools.map((tool, i) =>
        isHttp(tool) ? (
          <ToolCard
            key={ids[i]}
            tool={tool}
            index={i}
            errors={errors}
            disabled={disabled}
            secretNames={secretNames}
            onChange={(t) => update(i, t)}
            onRemove={() => {
              onValidity(ids[i]!, true)
              setIds((prev) => prev.filter((_, j) => j !== i))
              onChange({ ...config, tools: tools.filter((_, j) => j !== i) })
            }}
            onValidity={(valid) => onValidity(ids[i]!, valid)}
          />
        ) : (
          <Card key={ids[i]}>
            <CardContent className="flex items-center gap-2 py-4 text-sm">
              <Badge variant="secondary">Built-in</Badge>
              <span className="font-mono">{tool.name}</span>
            </CardContent>
          </Card>
        ),
      )}
    </div>
  )
}
