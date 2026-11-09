import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Loader2, Pause, Play, Square, Upload } from 'lucide-react'
import { useState } from 'react'
import type { ChangeEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { describeError } from '@/api/client'
import { useAuth } from '@/auth/AuthContext'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { CampaignStatusBadge, ProgressBar } from '@/pages/campaigns'
import { CONTACT_STATUS, DAY_NAMES, progress } from '@/lib/campaigns'
import { readTextFile } from '@/lib/files'

const PAGE = 50
const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })
const STATS = ['pending', 'calling', 'completed', 'no_answer', 'voicemail', 'failed', 'opted_out', 'dnc']

function AddContacts({ id }: { id: string }) {
  const { client } = useAuth()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [csv, setCsv] = useState('')
  const add = useMutation({
    mutationFn: () => client!.addContacts(id, { csv }),
    onSuccess: (r) => {
      void queryClient.invalidateQueries({ queryKey: ['campaign', id] })
      toast.success(`Added ${r.added} people${r.already_in_campaign ? `, ${r.already_in_campaign} were already in` : ''}${r.rejected.length ? `, ${r.rejected.length} rows skipped` : ''}`)
      setOpen(false)
      setCsv('')
    },
    onError: (e) => toast.error(describeError(e)),
  })
  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      setCsv(await readTextFile(file, 650_000))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not read that file.')
    }
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button variant="outline" size="sm" />}>
        <Upload /> Add people
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add people</DialogTitle>
          <DialogDescription>Same format as before: a header row with a phone column. Numbers already in the campaign are skipped.</DialogDescription>
        </DialogHeader>
        <Input aria-label="CSV file" type="file" accept=".csv,text/csv,text/plain" onChange={(e) => void onFile(e)} />
        <Textarea aria-label="CSV text" rows={6} value={csv} onChange={(e) => setCsv(e.target.value)} className="font-mono text-xs" />
        <DialogFooter>
          <Button disabled={!csv.trim() || add.isPending} onClick={() => add.mutate()}>
            {add.isPending && <Loader2 className="animate-spin" />}
            Add
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function CampaignDetailPage() {
  const { id = '' } = useParams()
  const { client, can } = useAuth()
  const queryClient = useQueryClient()
  const [filter, setFilter] = useState<string | null>(null)
  const [page, setPage] = useState(0)

  const campaign = useQuery({
    queryKey: ['campaign', id],
    queryFn: () => client!.campaign(id),
    enabled: !!client,
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 5000 : false),
  })
  const contacts = useQuery({
    queryKey: ['campaign', id, 'contacts', filter, page],
    queryFn: () => client!.campaignContacts(id, { status: filter ?? undefined, offset: page * PAGE, limit: PAGE }),
    enabled: !!client,
    refetchInterval: campaign.data?.status === 'running' ? 5000 : false,
  })
  const act = useMutation({
    mutationFn: (action: 'start' | 'pause' | 'resume' | 'cancel') => client!.campaignAction(id, action),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['campaign', id] })
      void queryClient.invalidateQueries({ queryKey: ['campaigns'] })
    },
    onError: (e) => toast.error(describeError(e)),
  })

  if (campaign.isPending) return <Skeleton className="mx-auto h-40 max-w-4xl" />
  if (campaign.isError) {
    return (
      <div className="mx-auto max-w-4xl">
        <Alert variant="destructive" role="alert"><AlertDescription>{describeError(campaign.error)}</AlertDescription></Alert>
      </div>
    )
  }
  const c = campaign.data
  const { total, done } = progress(c.counts)
  const runnable = can('campaigns:run')
  const finished = c.status === 'completed' || c.status === 'cancelled'
  const totalPages = Math.max(1, Math.ceil((contacts.data?.total ?? 0) / PAGE))

  return (
    <div className="mx-auto grid max-w-4xl gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="grid gap-1">
          <Link to="/campaigns" className="text-muted-foreground inline-flex items-center gap-1 text-sm hover:underline">
            <ArrowLeft className="size-3" /> Campaigns
          </Link>
          <h1 className="flex items-center gap-3 text-2xl font-semibold tracking-tight">
            {c.name} <CampaignStatusBadge status={c.status} />
          </h1>
          <p className="text-muted-foreground text-sm">
            {c.agent_name} calling from {c.from_number} · {c.days.map((d) => DAY_NAMES[d]).join(' ')} {c.window_start}–{c.window_end} ({c.timezone}) ·{' '}
            {c.max_concurrent} at a time · up to {c.max_attempts} tries, {c.retry_delay_min} min apart
          </p>
        </div>
        {runnable && !finished && (
          <div className="flex gap-2">
            {c.status === 'draft' && (
              <Button onClick={() => act.mutate('start')} disabled={act.isPending}>
                <Play /> Start
              </Button>
            )}
            {c.status === 'running' && (
              <Button variant="outline" onClick={() => act.mutate('pause')} disabled={act.isPending}>
                <Pause /> Pause
              </Button>
            )}
            {c.status === 'paused' && (
              <Button onClick={() => act.mutate('resume')} disabled={act.isPending}>
                <Play /> Resume
              </Button>
            )}
            <AlertDialog>
              <AlertDialogTrigger render={<Button variant="outline" />}>
                <Square /> Cancel campaign
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Cancel this campaign?</AlertDialogTitle>
                  <AlertDialogDescription>
                    No more calls will be placed. Calls already in progress finish normally. This can’t be undone.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Keep running</AlertDialogCancel>
                  <AlertDialogAction variant="destructive" onClick={() => act.mutate('cancel')}>
                    Cancel campaign
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        )}
      </div>

      <Card>
        <CardContent className="grid gap-4 pt-6">
          <ProgressBar counts={c.counts} />
          <p className="sr-only">{done} of {total} finished</p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" role="group" aria-label="Filter contacts by status">
            {STATS.map((s) => (
              <button
                key={s}
                type="button"
                aria-pressed={filter === s}
                onClick={() => { setFilter(filter === s ? null : s); setPage(0) }}
                className={'rounded-md border p-3 text-left transition-colors ' + (filter === s ? 'bg-accent' : 'hover:bg-accent/50')}
              >
                <span className="block text-xl font-semibold tabular-nums">{c.counts[s] ?? 0}</span>
                <span className="text-muted-foreground text-xs">{CONTACT_STATUS[s]}</span>
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium">People {filter && <Badge variant="secondary">{CONTACT_STATUS[filter]}</Badge>}</h2>
        {can('campaigns:manage_contacts') && !finished && <AddContacts id={id} />}
      </div>

      {contacts.isPending ? (
        <Skeleton className="h-24" />
      ) : (contacts.data?.items ?? []).length === 0 ? (
        <p className="text-muted-foreground text-sm">{filter ? 'Nobody has this status.' : 'No people yet. Add some to start.'}</p>
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Number</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Tries</TableHead>
                <TableHead>Next try</TableHead>
                <TableHead>Last call</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {contacts.data!.items.map((p) => (
                <TableRow key={p.id}>
                  <TableCell>{p.name || <span className="text-muted-foreground">—</span>}</TableCell>
                  <TableCell className="tabular-nums">{p.number}</TableCell>
                  <TableCell>
                    {CONTACT_STATUS[p.status] ?? p.status}
                    {p.last_error && <span className="text-muted-foreground block text-xs">{p.last_error}</span>}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{p.attempts}</TableCell>
                  <TableCell>{p.next_attempt_at ? dateTime.format(new Date(p.next_attempt_at)) : <span className="text-muted-foreground">—</span>}</TableCell>
                  <TableCell>
                    {p.last_call_id && can('calls:read') ? <Link className="underline underline-offset-4" to={`/calls/${p.last_call_id}`}>View</Link> : <span className="text-muted-foreground">—</span>}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-3 text-sm">
              <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</Button>
              <span className="tabular-nums">Page {page + 1} of {totalPages}</span>
              <Button variant="outline" size="sm" disabled={page + 1 >= totalPages} onClick={() => setPage(page + 1)}>Next</Button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
