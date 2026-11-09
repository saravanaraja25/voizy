import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Megaphone, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { describeError } from '@/api/client'
import type { CampaignOut } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { Field } from '@/components/field'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { CAMPAIGN_STATUS, progress } from '@/lib/campaigns'

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' })

export function CampaignStatusBadge({ status }: { status: CampaignOut['status'] }) {
  const label = CAMPAIGN_STATUS[status] ?? status
  if (status === 'running') return <Badge>{label}</Badge>
  if (status === 'cancelled') return <Badge variant="destructive">{label}</Badge>
  return <Badge variant={status === 'paused' ? 'secondary' : 'outline'}>{label}</Badge>
}

export function ProgressBar({ counts }: { counts: Record<string, number> }) {
  const { total, done } = progress(counts)
  const pct = total === 0 ? 0 : Math.round((done / total) * 100)
  return (
    <div className="grid gap-1" aria-label={`${done} of ${total} contacts finished`}>
      <div className="bg-muted h-2 overflow-hidden rounded-full">
        <div className="bg-primary h-full" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-muted-foreground text-xs tabular-nums">
        {done} of {total}
      </span>
    </div>
  )
}

function DoNotCall() {
  const { client, can } = useAuth()
  const queryClient = useQueryClient()
  const [number, setNumber] = useState('')
  const [note, setNote] = useState('')
  const list = useQuery({ queryKey: ['dnc'], queryFn: () => client!.dnc(), enabled: !!client })
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['dnc'] })
  const add = useMutation({
    mutationFn: () => client!.addDnc(number.replace(/[\s().-]/g, ''), note.trim()),
    onSuccess: () => {
      refresh()
      void queryClient.invalidateQueries({ queryKey: ['campaigns'] })
      setNumber('')
      setNote('')
      toast.success('Added to the do-not-call list')
    },
    onError: (e) => toast.error(describeError(e)),
  })
  const remove = useMutation({
    mutationFn: (n: string) => client!.removeDnc(n),
    onSuccess: refresh,
    onError: (e) => toast.error(describeError(e)),
  })
  const manage = can('campaigns:manage_contacts')

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (number.trim()) add.mutate()
  }

  return (
    <div className="grid gap-4">
      <p className="text-muted-foreground text-sm">
        These numbers are never called by any campaign, even if they are on a list. People who ask not to be
        called on a call are added automatically.
      </p>
      {manage && (
        <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-2">
          <Field label="Number" htmlFor="dnc-number" className="min-w-52">
            <Input id="dnc-number" value={number} onChange={(e) => setNumber(e.target.value)} placeholder="+14155550134" inputMode="tel" />
          </Field>
          <Field label="Note (optional)" htmlFor="dnc-note" className="min-w-52 flex-1">
            <Input id="dnc-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} />
          </Field>
          <Button type="submit" disabled={!number.trim() || add.isPending}>
            {add.isPending && <Loader2 className="animate-spin" />}
            Add
          </Button>
        </form>
      )}
      {list.isPending ? (
        <Skeleton className="h-10" />
      ) : (list.data ?? []).length === 0 ? (
        <p className="text-muted-foreground text-sm">Nobody is on the list.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Number</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>Note</TableHead>
              <TableHead>Added</TableHead>
              {manage && <TableHead className="text-right">Remove</TableHead>}
            </TableRow>
          </TableHeader>
          <TableBody>
            {list.data!.map((d) => (
              <TableRow key={d.number + d.created_at}>
                <TableCell className="tabular-nums">{d.number}</TableCell>
                <TableCell>{d.source === 'opt_out' ? 'Asked on a call' : d.source === 'manual' ? 'Added by hand' : d.source}</TableCell>
                <TableCell>{d.note || <span className="text-muted-foreground">—</span>}</TableCell>
                <TableCell>{dateFormat.format(new Date(d.created_at))}</TableCell>
                {manage && (
                  <TableCell className="text-right">
                    <Button variant="outline" size="icon" aria-label={`Remove ${d.number}`} onClick={() => remove.mutate(d.number)} disabled={d.number.includes('•')}>
                      <Trash2 />
                    </Button>
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}

export function CampaignsPage() {
  const { client, can } = useAuth()
  const campaigns = useQuery({ queryKey: ['campaigns'], queryFn: () => client!.campaigns(), enabled: !!client, refetchInterval: 10_000 })
  return (
    <div className="mx-auto grid max-w-5xl gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Campaigns</h1>
          <p className="text-muted-foreground text-sm">
            Call a list of people with an agent, inside the hours you choose, with retries.
          </p>
        </div>
        {can('campaigns:create') && (
          <Button render={<Link to="/campaigns/new" />}>
            <Plus /> New campaign
          </Button>
        )}
      </div>
      <Tabs defaultValue="campaigns">
        <TabsList>
          <TabsTrigger value="campaigns">Campaigns</TabsTrigger>
          <TabsTrigger value="dnc">Do not call</TabsTrigger>
        </TabsList>
        <TabsContent value="campaigns" className="pt-4">
          {campaigns.isError && (
            <Alert variant="destructive" role="alert">
              <AlertDescription>{describeError(campaigns.error)}</AlertDescription>
            </Alert>
          )}
          {campaigns.isPending ? (
            <Skeleton className="h-24" />
          ) : (campaigns.data ?? []).length === 0 ? (
            <Card>
              <CardContent className="grid justify-items-center gap-2 py-10 text-center text-sm">
                <Megaphone className="text-muted-foreground size-6" />
                <p>No campaigns yet.</p>
                <p className="text-muted-foreground max-w-md">
                  Upload a CSV of people and an agent will call them for you. You need a connected phone number first.
                </p>
              </CardContent>
            </Card>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Campaign</TableHead>
                  <TableHead>Agent</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="min-w-40">Progress</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {campaigns.data!.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell>
                      <Link className="font-medium underline-offset-4 hover:underline" to={`/campaigns/${c.id}`}>
                        {c.name}
                      </Link>
                    </TableCell>
                    <TableCell>{c.agent_name}</TableCell>
                    <TableCell>
                      <CampaignStatusBadge status={c.status} />
                    </TableCell>
                    <TableCell>
                      <ProgressBar counts={c.counts} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </TabsContent>
        <TabsContent value="dnc" className="pt-4">
          <DoNotCall />
        </TabsContent>
      </Tabs>
    </div>
  )
}
