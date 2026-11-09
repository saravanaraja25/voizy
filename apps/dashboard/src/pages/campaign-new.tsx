import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowLeft, Loader2 } from 'lucide-react'
import { useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { describeError } from '@/api/client'
import type { CsvPreview } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { Field } from '@/components/field'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button, buttonVariants } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { browserTimezone, DAY_NAMES } from '@/lib/campaigns'
import { readTextFile } from '@/lib/files'

const MAX_CSV = 650_000
const SAMPLE = 'name,phone,order_id\nAda Lovelace,+14155550134,1042\nBob Smith,+14155550199,1077\n'

function NumberField({ id, label, value, min, max, onChange, hint }: { id: string; label: string; value: number; min: number; max: number; onChange: (n: number) => void; hint?: string }) {
  return (
    <Field label={label} htmlFor={id} hint={hint}>
      <Input id={id} type="number" min={min} max={max} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </Field>
  )
}

export function CampaignNewPage() {
  const { client } = useAuth()
  const navigate = useNavigate()
  const agents = useQuery({ queryKey: ['agents'], queryFn: () => client!.listAgents(), enabled: !!client })
  const numbers = useQuery({ queryKey: ['phone-numbers'], queryFn: () => client!.phoneNumbers(), enabled: !!client })
  const live = (agents.data ?? []).filter((a) => !a.archived && a.published_version != null)

  const [name, setName] = useState('')
  const [agentId, setAgentId] = useState<string | null>(null)
  const [numberId, setNumberId] = useState<string | null>(null)
  const [timezone, setTimezone] = useState(browserTimezone())
  const [days, setDays] = useState<number[]>([0, 1, 2, 3, 4])
  const [start, setStart] = useState('09:00')
  const [end, setEnd] = useState('17:00')
  const [concurrent, setConcurrent] = useState(1)
  const [attempts, setAttempts] = useState(2)
  const [retry, setRetry] = useState(60)
  const [csv, setCsv] = useState('')
  const [country, setCountry] = useState('')
  const [consent, setConsent] = useState(false)
  const [preview, setPreview] = useState<CsvPreview | null>(null)

  const toggleDay = (d: number) => setDays((cur) => (cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d].sort()))
  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      setCsv(await readTextFile(file, MAX_CSV))
      setPreview(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not read that file.')
    }
  }
  const cc = country.trim() || undefined

  const check = useMutation({
    mutationFn: () => client!.previewCsv({ csv, default_country_code: cc, agent_id: agentId ?? undefined }),
    onSuccess: setPreview,
    onError: (e) => toast.error(describeError(e)),
  })
  const create = useMutation({
    mutationFn: () =>
      client!.createCampaign({
        name: name.trim(),
        agent_id: agentId!,
        from_number_id: numberId!,
        timezone: timezone.trim(),
        days,
        window_start: start,
        window_end: end,
        max_concurrent: concurrent,
        max_attempts: attempts,
        retry_delay_min: retry,
        consent_confirmed: consent,
        csv: csv.trim() || undefined,
        default_country_code: cc,
      }),
    onSuccess: (r) => {
      toast.success(`Created “${r.campaign.name}”${r.import_report ? ` with ${r.import_report.added} contacts` : ''}`)
      navigate(`/campaigns/${r.campaign.id}`)
    },
    onError: (e) => toast.error(describeError(e)),
  })

  const agentItems = live.map((a) => ({ value: a.id, label: a.name }))
  const numberItems = (numbers.data ?? []).map((n) => ({ value: n.id, label: n.label ? `${n.e164} · ${n.label}` : n.e164 }))
  const ready = name.trim() !== '' && agentId != null && numberId != null && days.length > 0 && start < end && consent
  function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (ready) create.mutate()
  }

  return (
    <form onSubmit={onSubmit} className="mx-auto grid max-w-3xl gap-6">
      <div className="grid gap-1">
        <Link to="/campaigns" className="text-muted-foreground inline-flex items-center gap-1 text-sm hover:underline">
          <ArrowLeft className="size-3" /> Campaigns
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">New campaign</h1>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Who calls, and from where</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <Field label="Name" htmlFor="c-name" className="md:col-span-2">
            <Input id="c-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={100} required />
          </Field>
          <Field label="Agent" htmlFor="c-agent" hint={live.length === 0 ? 'Publish an agent first.' : 'Only published agents appear.'}>
            <Select value={agentId ?? ''} items={agentItems} onValueChange={(v) => setAgentId(v || null)}>
              <SelectTrigger id="c-agent" className="w-full">
                <SelectValue placeholder="Choose an agent" />
              </SelectTrigger>
              <SelectContent>
                {agentItems.map((i) => (
                  <SelectItem key={i.value} value={i.value}>{i.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Call from" htmlFor="c-number" hint={numberItems.length === 0 ? 'Connect a phone number first.' : undefined}>
            <Select value={numberId ?? ''} items={numberItems} onValueChange={(v) => setNumberId(v || null)}>
              <SelectTrigger id="c-number" className="w-full">
                <SelectValue placeholder="Choose a number" />
              </SelectTrigger>
              <SelectContent>
                {numberItems.map((i) => (
                  <SelectItem key={i.value} value={i.value}>{i.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>When to call</CardTitle>
          <CardDescription>Calls only go out inside this window, in each person’s own timezone.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <div className="grid gap-2 md:col-span-2" role="group" aria-label="Calling days">
            <span className="text-sm font-medium">Days</span>
            <div className="flex flex-wrap gap-2">
              {DAY_NAMES.map((d, i) => (
                <Button key={d} type="button" size="sm" variant={days.includes(i) ? 'default' : 'outline'} aria-pressed={days.includes(i)} onClick={() => toggleDay(i)}>
                  {d}
                </Button>
              ))}
            </div>
          </div>
          <Field label="From" htmlFor="c-start"><Input id="c-start" type="time" value={start} onChange={(e) => setStart(e.target.value)} required /></Field>
          <Field label="Until" htmlFor="c-end" error={start < end ? undefined : 'Must be after the start time.'}><Input id="c-end" type="time" value={end} onChange={(e) => setEnd(e.target.value)} required /></Field>
          <Field label="Default timezone" htmlFor="c-tz" hint="Used for people without a timezone column, like Asia/Kolkata." className="md:col-span-2">
            <Input id="c-tz" value={timezone} onChange={(e) => setTimezone(e.target.value)} />
          </Field>
          <NumberField id="c-conc" label="Calls at the same time" value={concurrent} min={1} max={10} onChange={setConcurrent} hint="LiveKit's free plan allows about 5 at once." />
          <NumberField id="c-att" label="Attempts per person" value={attempts} min={1} max={5} onChange={setAttempts} hint="Counts the first call." />
          <NumberField id="c-retry" label="Wait before retrying (minutes)" value={retry} min={5} max={10080} onChange={setRetry} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Who to call</CardTitle>
          <CardDescription>
            A CSV with a <code>phone</code> column. Optional: <code>name</code>, <code>timezone</code> (like America/New_York), and any other
            column fills a prompt variable of the same name that the agent declares.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <Field label="CSV file" htmlFor="c-file"><Input id="c-file" type="file" accept=".csv,text/csv,text/plain" onChange={(e) => void onFile(e)} /></Field>
          <Field label="…or paste it" htmlFor="c-csv" hint="Numbers need a country code like +14155550134, or set a default below.">
            <Textarea id="c-csv" rows={5} value={csv} placeholder={SAMPLE} onChange={(e) => { setCsv(e.target.value); setPreview(null) }} className="font-mono text-xs" />
          </Field>
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Default country code (optional)" htmlFor="c-cc" className="w-56"><Input id="c-cc" value={country} onChange={(e) => setCountry(e.target.value)} placeholder="+1" /></Field>
            <Button type="button" variant="outline" disabled={!csv.trim() || check.isPending} onClick={() => check.mutate()}>
              {check.isPending && <Loader2 className="animate-spin" />}
              Check the list
            </Button>
          </div>
          {preview && (
            <Alert role="status">
              <AlertTitle>{preview.accepted} people will be called</AlertTitle>
              <AlertDescription className="grid gap-2">
                {preview.rejected.length > 0 && (
                  <p>
                    {preview.rejected.length} {preview.rejected.length === 1 ? 'row' : 'rows'} skipped:{' '}
                    {preview.rejected.slice(0, 5).map(([line, why]) => `line ${line} (${why})`).join('; ')}
                    {preview.rejected.length > 5 ? '…' : ''}
                  </p>
                )}
                {preview.ignored_columns.length > 0 && (
                  <p>Columns the agent does not use: {preview.ignored_columns.join(', ')}</p>
                )}
                {preview.sample.length > 0 && (
                  <Table>
                    <TableHeader>
                      <TableRow>{Object.keys(preview.sample[0]!).map((k) => <TableHead key={k}>{k}</TableHead>)}</TableRow>
                    </TableHeader>
                    <TableBody>
                      {preview.sample.map((row, i) => (
                        <TableRow key={i}>{Object.keys(preview.sample[0]!).map((k) => <TableCell key={k}>{row[k] ?? ''}</TableCell>)}</TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-1" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
        <span>I confirm the people on this list have agreed to be contacted by phone, and that calling them in these hours is allowed where they live.</span>
      </label>
      <div className="flex gap-2">
        <Button type="submit" disabled={!ready || create.isPending}>
          {create.isPending && <Loader2 className="animate-spin" />}
          Create campaign
        </Button>
        <Link to="/campaigns" className={buttonVariants({ variant: 'outline' })}>Cancel</Link>
      </div>
      <p className="text-muted-foreground text-xs">It is created as a draft. Nothing is called until you press Start.</p>
    </form>
  )
}
