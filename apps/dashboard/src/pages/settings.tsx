import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, KeyRound, Loader2, Pencil, Plug, Plus, Trash2, XCircle } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { toast } from 'sonner'
import { ApiError, describeError } from '@/api/client'
import type { IntegrationOut, TestResultOut, ToolSecretOut } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { Field } from '@/components/field'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' })

function StorageNotConfigured() {
  return (
    <Alert variant="destructive">
      <AlertTitle>Secret storage is not set up</AlertTitle>
      <AlertDescription className="grid gap-2">
        <span>
          Keys are stored encrypted, which needs an encryption key on the server. Generate one,
          add it to the server&apos;s environment, and restart the API:
        </span>
        <code className="bg-muted text-foreground rounded px-2 py-1 text-xs">voizy-admin generate-secret-key</code>
      </AlertDescription>
    </Alert>
  )
}

const isUnavailable = (e: unknown) => e instanceof ApiError && e.status === 503

// ---- integrations -------------------------------------------------------------------------

function IntegrationDialog({
  integration,
  open,
  onOpenChange,
}: {
  integration: IntegrationOut
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { client } = useAuth()
  const queryClient = useQueryClient()
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(integration.fields.map((f) => [f.name, f.secret ? '' : (f.value ?? '')])),
  )

  const save = useMutation({
    mutationFn: () => {
      // Send only what changed: a blank secret means "keep what is stored".
      const changed = Object.fromEntries(
        integration.fields
          .filter((f) => values[f.name]?.trim() && values[f.name] !== (f.secret ? '' : (f.value ?? '')))
          .map((f) => [f.name, values[f.name]!.trim()]),
      )
      return client.saveIntegration(integration.id, changed)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['integrations'] })
      toast.success(`${integration.label} saved`)
      onOpenChange(false)
    },
    onError: (e) => toast.error(describeError(e)),
  })

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={onSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{integration.label}</DialogTitle>
            <DialogDescription>
              Keys are stored encrypted and can never be read back. Leave a field blank to keep
              what is saved.
            </DialogDescription>
          </DialogHeader>
          {integration.fields.map((f) => (
            <Field key={f.name} label={f.label} htmlFor={`int-${f.name}`} hint={f.help || undefined}>
              <Input
                id={`int-${f.name}`}
                type={f.secret ? 'password' : 'text'}
                value={values[f.name] ?? ''}
                placeholder={f.secret && f.configured ? `${f.hint} (saved)` : f.placeholder}
                onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))}
                autoComplete="off"
                spellCheck={false}
              />
            </Field>
          ))}
          <DialogFooter>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending && <Loader2 className="animate-spin" />} Save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function IntegrationCard({ integration }: { integration: IntegrationOut }) {
  const { client } = useAuth()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [confirmRemove, setConfirmRemove] = useState(false)
  const [result, setResult] = useState<TestResultOut | null>(null)

  const test = useMutation({
    mutationFn: () => client.testIntegration(integration.id),
    onSuccess: setResult,
    onError: (e) => setResult({ ok: false, message: describeError(e) }),
  })
  const remove = useMutation({
    mutationFn: () => client.removeIntegration(integration.id),
    onSuccess: () => {
      setResult(null)
      void queryClient.invalidateQueries({ queryKey: ['integrations'] })
      toast.success(`${integration.label} disconnected`)
    },
    onError: (e) => toast.error(describeError(e)),
  })

  const anySaved = integration.fields.some((f) => f.configured)
  const status = integration.configured ? 'Connected' : anySaved ? 'Incomplete' : 'Not connected'

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2">
            <Plug className="size-4" /> {integration.label}
          </CardTitle>
          <Badge variant={integration.configured ? 'default' : anySaved ? 'outline' : 'secondary'}>{status}</Badge>
        </div>
        <CardDescription>{integration.description}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        <dl className="grid gap-1 text-sm">
          {integration.fields.map((f) => (
            <div key={f.name} className="flex justify-between gap-4">
              <dt className="text-muted-foreground">{f.label}</dt>
              <dd className="truncate font-mono text-xs">
                {f.configured ? (f.secret ? f.hint : f.value) : <span className="text-muted-foreground">not set</span>}
              </dd>
            </div>
          ))}
        </dl>
        <p className="text-muted-foreground text-xs">Used for: {integration.used_for}</p>
        {result && (
          <Alert variant={result.ok ? 'default' : 'destructive'} role={result.ok ? 'status' : 'alert'}>
            {result.ok ? <CheckCircle2 /> : <XCircle />}
            <AlertDescription>{result.message}</AlertDescription>
          </Alert>
        )}
      </CardContent>
      <CardFooter className="flex flex-wrap gap-2">
        <Button size="sm" onClick={() => setEditing(true)}>
          <Pencil /> {anySaved ? 'Edit' : 'Connect'}
        </Button>
        {integration.configured && (
          <Button size="sm" variant="outline" onClick={() => test.mutate()} disabled={test.isPending}>
            {test.isPending && <Loader2 className="animate-spin" />} Test connection
          </Button>
        )}
        {anySaved && (
          <Button size="sm" variant="ghost" onClick={() => setConfirmRemove(true)}>
            <Trash2 /> Remove
          </Button>
        )}
      </CardFooter>
      {editing && <IntegrationDialog integration={integration} open onOpenChange={setEditing} />}
      <AlertDialog open={confirmRemove} onOpenChange={setConfirmRemove}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Disconnect {integration.label}?</AlertDialogTitle>
            <AlertDialogDescription>
              The saved keys are deleted. Anything that depends on this connection stops working
              until you connect it again.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => remove.mutate()}>Disconnect</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}

function IntegrationsPanel() {
  const { client } = useAuth()
  const integrations = useQuery({ queryKey: ['integrations'], queryFn: () => client.integrations() })

  if (integrations.isError) {
    return isUnavailable(integrations.error) ? (
      <StorageNotConfigured />
    ) : (
      <Alert variant="destructive">
        <AlertTitle>Could not load integrations</AlertTitle>
        <AlertDescription>{describeError(integrations.error)}</AlertDescription>
      </Alert>
    )
  }
  if (integrations.isPending) {
    return (
      <div className="grid gap-4 md:grid-cols-2" aria-busy="true" aria-label="Loading integrations">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-48 w-full" />
        ))}
      </div>
    )
  }
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {integrations.data.map((i) => (
        <IntegrationCard key={i.id} integration={i} />
      ))}
    </div>
  )
}

// ---- tool credentials ---------------------------------------------------------------------

function parseHosts(text: string): string[] {
  return text
    .split(/[\s,]+/)
    .map((h) => h.trim())
    .filter(Boolean)
}

function CredentialDialog({
  existing,
  open,
  onOpenChange,
}: {
  existing: ToolSecretOut | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { client } = useAuth()
  const queryClient = useQueryClient()
  const [name, setName] = useState(existing?.name ?? '')
  const [value, setValue] = useState('')
  const [hosts, setHosts] = useState((existing?.allowed_hosts ?? []).join('\n'))
  const [description, setDescription] = useState(existing?.description ?? '')

  const save = useMutation({
    mutationFn: () =>
      client.putToolSecret(name.trim(), {
        value: value ? value : undefined,
        allowed_hosts: parseHosts(hosts),
        description: description.trim(),
      }),
    onSuccess: (s) => {
      void queryClient.invalidateQueries({ queryKey: ['secrets'] })
      toast.success(`Credential “${s.name}” saved`)
      onOpenChange(false)
    },
    onError: (e) => toast.error(describeError(e)),
  })

  const ready = name.trim() && parseHosts(hosts).length > 0 && (existing || value)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            if (ready) save.mutate()
          }}
          className="grid gap-4"
        >
          <DialogHeader>
            <DialogTitle>{existing ? `Edit ${existing.name}` : 'Add a tool credential'}</DialogTitle>
            <DialogDescription>
              A tool refers to this credential by name. The value is stored encrypted, never shown
              again, and only ever sent to the hosts you list.
            </DialogDescription>
          </DialogHeader>
          <Field label="Name" htmlFor="cred-name" hint="Lowercase letters, digits and underscores, e.g. clinic_api_key.">
            <Input id="cred-name" value={name} onChange={(e) => setName(e.target.value)} readOnly={!!existing} spellCheck={false} autoFocus={!existing} />
          </Field>
          <Field
            label="Value"
            htmlFor="cred-value"
            hint={existing ? `Leave blank to keep the saved value (${existing.hint}).` : 'The API key or token.'}
          >
            <Input id="cred-value" type="password" value={value} onChange={(e) => setValue(e.target.value)} autoComplete="off" />
          </Field>
          <Field
            label="Allowed hosts"
            htmlFor="cred-hosts"
            hint="One per line: api.example.com, or *.example.com for any subdomain. The credential is refused for every other address."
          >
            <Textarea id="cred-hosts" value={hosts} onChange={(e) => setHosts(e.target.value)} rows={3} spellCheck={false} />
          </Field>
          <Field label="Description" htmlFor="cred-desc">
            <Input id="cred-desc" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={200} />
          </Field>
          <DialogFooter>
            <Button type="submit" disabled={!ready || save.isPending}>
              {save.isPending && <Loader2 className="animate-spin" />} Save credential
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function CredentialsPanel() {
  const { client } = useAuth()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<ToolSecretOut | 'new' | null>(null)
  const [removing, setRemoving] = useState<ToolSecretOut | null>(null)
  const secrets = useQuery({ queryKey: ['secrets'], queryFn: () => client.toolSecrets() })
  const remove = useMutation({
    mutationFn: (name: string) => client.deleteToolSecret(name),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['secrets'] })
      toast.success('Credential deleted')
    },
    onError: (e) => toast.error(describeError(e)),
  })

  if (secrets.isError) {
    return isUnavailable(secrets.error) ? (
      <StorageNotConfigured />
    ) : (
      <Alert variant="destructive">
        <AlertTitle>Could not load credentials</AlertTitle>
        <AlertDescription>{describeError(secrets.error)}</AlertDescription>
      </Alert>
    )
  }

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div className="grid gap-1">
          <CardTitle>Tool credentials</CardTitle>
          <CardDescription>
            API keys your agents&apos; HTTP tools send to other services. Pick one in a tool&apos;s
            Authentication section. Each is locked to the hosts you allow, so a credential can&apos;t be
            sent anywhere else.
          </CardDescription>
        </div>
        <Button onClick={() => setEditing('new')}>
          <Plus /> Add credential
        </Button>
      </CardHeader>
      <CardContent>
        {secrets.isPending ? (
          <Skeleton className="h-24 w-full" aria-busy="true" aria-label="Loading credentials" />
        ) : secrets.data.length === 0 ? (
          <div className="text-muted-foreground flex flex-col items-center gap-2 py-8 text-sm">
            <KeyRound className="size-6" /> No credentials yet.
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Sent only to</TableHead>
                <TableHead className="hidden md:table-cell">Value</TableHead>
                <TableHead className="hidden md:table-cell">Updated</TableHead>
                <TableHead className="w-24 text-right">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {secrets.data.map((s) => (
                <TableRow key={s.name}>
                  <TableCell>
                    <div className="font-mono text-sm">{s.name}</div>
                    {s.description && <div className="text-muted-foreground text-xs">{s.description}</div>}
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {s.allowed_hosts.map((h) => (
                        <Badge key={h} variant="outline" className="font-mono">
                          {h}
                        </Badge>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell className="text-muted-foreground hidden font-mono text-xs md:table-cell">{s.hint}</TableCell>
                  <TableCell className="text-muted-foreground hidden md:table-cell">{dateFormat.format(new Date(s.updated_at))}</TableCell>
                  <TableCell className="text-right">
                    <Button variant="ghost" size="icon" aria-label={`Edit ${s.name}`} onClick={() => setEditing(s)}>
                      <Pencil />
                    </Button>
                    <Button variant="ghost" size="icon" aria-label={`Delete ${s.name}`} onClick={() => setRemoving(s)}>
                      <Trash2 />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
      {editing && (
        <CredentialDialog
          key={editing === 'new' ? 'new' : editing.name}
          existing={editing === 'new' ? null : editing}
          open
          onOpenChange={(o) => !o && setEditing(null)}
        />
      )}
      <AlertDialog open={removing != null} onOpenChange={(o) => !o && setRemoving(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {removing?.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              Tools that use it will fail until you add a credential with this name again.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (removing) remove.mutate(removing.name)
                setRemoving(null)
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}

export function SettingsPage() {
  const { can } = useAuth()
  if (!can('provider_keys:manage')) {
    return (
      <Alert className="mx-auto max-w-2xl">
        <AlertTitle>No access</AlertTitle>
        <AlertDescription>You need the “manage keys” permission to open settings.</AlertDescription>
      </Alert>
    )
  }
  return (
    <div className="mx-auto grid max-w-5xl gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-muted-foreground text-sm">Connect your own accounts. Everything here is stored encrypted.</p>
      </div>
      <Tabs defaultValue="integrations">
        <TabsList className="mb-4">
          <TabsTrigger value="integrations">Integrations</TabsTrigger>
          <TabsTrigger value="credentials">Tool credentials</TabsTrigger>
        </TabsList>
        <TabsContent value="integrations">
          <IntegrationsPanel />
        </TabsContent>
        <TabsContent value="credentials">
          <CredentialsPanel />
        </TabsContent>
      </Tabs>
    </div>
  )
}
