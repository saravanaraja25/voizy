import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { describeError } from '@/api/client'
import type { CallOut } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatDuration, SOURCE_LABEL, STATUS_LABEL } from '@/lib/calls'

const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })
const ALL = 'all'
const STATUS_ITEMS = [
  { value: ALL, label: 'Any status' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'in_progress', label: 'In progress' },
]

export function StatusBadge({ status }: { status: CallOut['status'] }) {
  const label = STATUS_LABEL[status] ?? status
  if (status === 'failed') return <Badge variant="destructive">{label}</Badge>
  if (status === 'in_progress') return <Badge variant="secondary">{label}</Badge>
  return <Badge variant="outline">{label}</Badge>
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="text-muted-foreground text-sm font-normal">{label}</CardTitle>
      </CardHeader>
      <CardContent className="text-2xl font-semibold">{value}</CardContent>
    </Card>
  )
}

export function CallsPage() {
  const { client } = useAuth()
  const [params, setParams] = useSearchParams()
  const agentId = params.get('agent_id') ?? ALL
  const status = params.get('status') ?? ALL

  function setFilter(key: string, value: string | null) {
    const next = new URLSearchParams(params)
    if (!value || value === ALL) next.delete(key)
    else next.set(key, value)
    setParams(next, { replace: true })
  }

  const agents = useQuery({ queryKey: ['agents'], queryFn: () => client!.listAgents(), enabled: !!client })
  const summary = useQuery({
    queryKey: ['calls', 'summary'],
    queryFn: () => client!.callSummary(7),
    enabled: !!client,
  })
  const list = useInfiniteQuery({
    queryKey: ['calls', 'list', agentId, status],
    queryFn: ({ pageParam }) =>
      client!.calls({
        agent_id: agentId === ALL ? undefined : agentId,
        status: status === ALL ? undefined : status,
        cursor: pageParam,
      }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled: !!client,
  })

  const rows = list.data?.pages.flatMap((p) => p.items) ?? []
  const agentItems = [
    { value: ALL, label: 'All agents' },
    ...(agents.data ?? []).map((a) => ({ value: a.id, label: a.name })),
  ]
  const s = summary.data

  return (
    <div className="mx-auto grid max-w-5xl gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Calls</h1>
        <p className="text-muted-foreground text-sm">
          Every conversation your agents have had. Transcripts are redacted and expire according to
          each agent’s retention policy.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="Last 7 days">
        <Stat label="Calls, last 7 days" value={s ? String(s.total) : '—'} />
        <Stat label="Completed" value={s ? String(s.completed) : '—'} />
        <Stat label="Average length" value={formatDuration(s?.avg_duration_s)} />
        <Stat label="Median response" value={s?.median_latency_ms != null ? `${s.median_latency_ms} ms` : '—'} />
      </div>

      <div className="flex flex-wrap gap-2">
        <Select value={agentId} items={agentItems} onValueChange={(v) => setFilter('agent_id', v)}>
          <SelectTrigger className="w-52" aria-label="Filter by agent">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {agentItems.map((i) => (
              <SelectItem key={i.value} value={i.value}>
                {i.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={status} items={STATUS_ITEMS} onValueChange={(v) => setFilter('status', v)}>
          <SelectTrigger className="w-44" aria-label="Filter by status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUS_ITEMS.map((i) => (
              <SelectItem key={i.value} value={i.value}>
                {i.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {list.isError && (
        <Alert variant="destructive" role="alert">
          <AlertDescription>{describeError(list.error)}</AlertDescription>
        </Alert>
      )}

      {list.isPending ? (
        <div className="grid gap-2" role="status" aria-label="Loading calls">
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
        </div>
      ) : rows.length === 0 ? (
        <Card>
          <CardContent className="text-muted-foreground py-10 text-center text-sm">
            No calls yet. Start a test call from an agent’s page and it will appear here.
          </CardContent>
        </Card>
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Started</TableHead>
                <TableHead>Agent</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Length</TableHead>
                <TableHead className="text-right">Response</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((c) => (
                <TableRow key={c.id}>
                  <TableCell>
                    <Link className="font-medium underline-offset-4 hover:underline" to={`/calls/${c.id}`}>
                      {dateTime.format(new Date(c.started_at))}
                    </Link>
                  </TableCell>
                  <TableCell>
                    {c.agent_name} <span className="text-muted-foreground">v{c.agent_version}</span>
                  </TableCell>
                  <TableCell>{SOURCE_LABEL[c.source] ?? c.source}</TableCell>
                  <TableCell>
                    <StatusBadge status={c.status} />
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{formatDuration(c.duration_s)}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {c.latency_p50_ms != null ? `${c.latency_p50_ms} ms` : '—'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {list.hasNextPage && (
            <Button
              variant="outline"
              className="justify-self-center"
              onClick={() => void list.fetchNextPage()}
              disabled={list.isFetchingNextPage}
            >
              {list.isFetchingNextPage ? 'Loading…' : 'Load more'}
            </Button>
          )}
        </>
      )}
    </div>
  )
}
