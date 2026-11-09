import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Trash2, Wrench } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { describeError } from '@/api/client'
import type { TurnOut } from '@/api/types'
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
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDuration, SOURCE_LABEL } from '@/lib/calls'
import { TARGET_MS } from '@/lib/latency'
import { StatusBadge } from '@/pages/calls'

const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'medium' })

function Bubble({ turn }: { turn: TurnOut }) {
  if (turn.role === 'tool') {
    return (
      <li className="text-muted-foreground flex items-center justify-center gap-1.5 text-xs">
        <Wrench className="size-3" />
        Used <span className="font-medium">{turn.tool_name}</span>
        {turn.tool_ok === false ? ' — failed' : ''}
        {turn.tool_ms != null ? ` · ${turn.tool_ms} ms` : ''}
      </li>
    )
  }
  const caller = turn.role === 'user'
  return (
    <li className={caller ? 'flex justify-end' : 'flex justify-start'}>
      <div
        className={
          'max-w-[80%] rounded-2xl px-3 py-2 text-sm ' +
          (caller ? 'bg-primary text-primary-foreground' : 'bg-muted')
        }
      >
        <span className="sr-only">{caller ? 'Caller: ' : 'Agent: '}</span>
        {turn.text || <span className="italic opacity-70">(not recorded)</span>}
      </div>
    </li>
  )
}

function LatencyBars({ turns }: { turns: TurnOut[] }) {
  const points = turns.flatMap((t) => (t.latency?.e2e != null ? [t.latency.e2e] : []))
  if (points.length === 0) return null
  const max = Math.max(...points, TARGET_MS)
  return (
    <Card>
      <CardHeader>
        <CardTitle>Response time per turn</CardTitle>
        <CardDescription>Target is under {TARGET_MS} ms. Excludes network delivery to the caller.</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="flex h-24 items-end gap-1" aria-label="Response time per agent turn">
          {points.map((ms, i) => (
            <li
              key={i}
              title={`${ms} ms`}
              className={'min-w-2 flex-1 rounded-t ' + (ms <= TARGET_MS ? 'bg-emerald-500' : 'bg-amber-500')}
              style={{ height: `${Math.max(4, (ms / max) * 100)}%` }}
            >
              <span className="sr-only">{ms} ms</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}

export function CallDetailPage() {
  const { id = '' } = useParams()
  const { client, can } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ['calls', 'detail', id],
    queryFn: () => client!.call(id),
    enabled: !!client,
  })
  const remove = useMutation({
    mutationFn: () => client!.deleteCall(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['calls'] })
      toast.success('Call deleted')
      navigate('/calls', { replace: true })
    },
    onError: (e) => toast.error(describeError(e)),
  })

  if (query.isPending) {
    return (
      <div className="mx-auto grid max-w-3xl gap-3" role="status" aria-label="Loading call">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40" />
      </div>
    )
  }
  if (query.isError) {
    return (
      <div className="mx-auto max-w-3xl">
        <Alert variant="destructive" role="alert">
          <AlertDescription>{describeError(query.error)}</AlertDescription>
        </Alert>
      </div>
    )
  }

  const { call, turns, transcript_visible } = query.data
  const spoken = turns.filter((t) => t.role !== 'tool' || t.tool_name)
  return (
    <div className="mx-auto grid max-w-3xl gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="grid gap-1">
          <Link to="/calls" className="text-muted-foreground inline-flex items-center gap-1 text-sm hover:underline">
            <ArrowLeft className="size-3" /> All calls
          </Link>
          <h1 className="text-2xl font-semibold tracking-tight">
            {call.agent_name} <span className="text-muted-foreground text-lg">v{call.agent_version}</span>
          </h1>
          <p className="text-muted-foreground text-sm">
            {dateTime.format(new Date(call.started_at))} · {SOURCE_LABEL[call.source] ?? call.source} ·{' '}
            {formatDuration(call.duration_s)}
          </p>
          {call.remote_number && (
            <p className="text-sm">
              <span className="text-muted-foreground">
                {call.source === 'outbound' ? 'Called' : 'Caller'}:{' '}
              </span>
              <span className="font-medium tabular-nums">{call.remote_number}</span>
              {call.remote_number_masked && (
                <span className="text-muted-foreground"> (full number hidden for your role)</span>
              )}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={call.status} />
          {can('calls:delete') && (
            <AlertDialog>
              <AlertDialogTrigger render={<Button variant="outline" size="sm" />}>
                <Trash2 /> Delete
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Delete this call?</AlertDialogTitle>
                  <AlertDialogDescription>
                    The record and its transcript are removed permanently. This can’t be undone.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction variant="destructive" onClick={() => remove.mutate()}>
                    Delete call
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
        </div>
      </div>

      <LatencyBars turns={turns} />

      <Card>
        <CardHeader>
          <CardTitle>Transcript</CardTitle>
          <CardDescription>
            {call.turn_count} turns · personal details are redacted on a best-effort basis
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!transcript_visible ? (
            <p className="text-muted-foreground text-sm">You don’t have permission to view transcripts.</p>
          ) : !call.transcript_stored ? (
            <p className="text-muted-foreground text-sm">
              This agent doesn’t keep transcripts, so only call details were saved.
            </p>
          ) : spoken.length === 0 ? (
            <p className="text-muted-foreground text-sm">Nothing was said on this call.</p>
          ) : (
            <ol className="grid gap-2" aria-label="Transcript">
              {spoken.map((t) => (
                <Bubble key={t.seq} turn={t} />
              ))}
            </ol>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
