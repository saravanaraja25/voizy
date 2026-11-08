import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Phone, PhoneOutgoing, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { describeError } from '@/api/client'
import type { AgentOut, PhoneNumberOut } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { Field } from '@/components/field'
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

const NOBODY = 'none'
const E164 = /^\+[1-9][0-9]{6,14}$/

/** People type "+1 415 555 0134" or "(415) 555-0134"; the API wants E.164 without spaces. */
export function normalizeNumber(raw: string): string {
  const trimmed = raw.trim()
  const digits = trimmed.replace(/[^\d]/g, '')
  return trimmed.startsWith('+') ? `+${digits}` : digits
}

function liveAgents(agents: AgentOut[] | undefined) {
  return (agents ?? []).filter((a) => !a.archived && a.published_version != null)
}

function AgentSelect({
  id,
  agents,
  value,
  onChange,
  disabled,
  nobodyLabel = 'No one (reject calls)',
}: {
  id: string
  agents: AgentOut[]
  value: string | null
  onChange: (id: string | null) => void
  disabled?: boolean
  nobodyLabel?: string
}) {
  const items = [
    { value: NOBODY, label: nobodyLabel },
    ...agents.map((a) => ({ value: a.id, label: a.name })),
  ]
  return (
    <Select
      value={value ?? NOBODY}
      items={items}
      disabled={disabled}
      onValueChange={(v) => v && onChange(v === NOBODY ? null : v)}
    >
      <SelectTrigger id={id} className="w-full min-w-44" aria-label="Agent that answers">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {items.map((i) => (
          <SelectItem key={i.value} value={i.value}>
            {i.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function ConnectDialog({ agents }: { agents: AgentOut[] }) {
  const { client } = useAuth()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [number, setNumber] = useState('')
  const [label, setLabel] = useState('')
  const [agentId, setAgentId] = useState<string | null>(null)
  const e164 = normalizeNumber(number)

  const connect = useMutation({
    mutationFn: () => client!.connectNumber({ e164, label: label.trim(), agent_id: agentId }),
    onSuccess: (n) => {
      void queryClient.invalidateQueries({ queryKey: ['phone-numbers'] })
      toast.success(`Connected ${n.e164}`)
      setOpen(false)
      setNumber('')
      setLabel('')
      setAgentId(null)
    },
    onError: (e) => toast.error(describeError(e)),
  })

  function onSubmit(ev: FormEvent) {
    ev.preventDefault()
    if (E164.test(e164)) connect.mutate()
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button />}>
        <Plus /> Connect a number
      </DialogTrigger>
      <DialogContent>
        <form onSubmit={onSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Connect a Twilio number</DialogTitle>
            <DialogDescription>
              The number must already be in your Twilio account. Voizy sets up the SIP trunk and
              routes calls to LiveKit. It replaces any voice webhook on that number.
            </DialogDescription>
          </DialogHeader>
          <Field
            label="Phone number"
            htmlFor="phone-e164"
            hint="International format, e.g. +14155550134."
            error={number && !E164.test(e164) ? 'Enter the number with its country code.' : undefined}
          >
            <Input
              id="phone-e164"
              value={number}
              onChange={(e) => setNumber(e.target.value)}
              inputMode="tel"
              autoComplete="off"
              autoFocus
              required
            />
          </Field>
          <Field label="Label (optional)" htmlFor="phone-label">
            <Input
              id="phone-label"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              maxLength={80}
              placeholder="e.g. Main line"
            />
          </Field>
          <Field
            label="Who answers"
            htmlFor="phone-agent"
            hint={agents.length === 0 ? 'Publish an agent to let it answer calls.' : 'Only published agents appear.'}
          >
            <AgentSelect id="phone-agent" agents={agents} value={agentId} onChange={setAgentId} />
          </Field>
          <DialogFooter>
            <Button type="submit" disabled={connect.isPending || !E164.test(e164)}>
              {connect.isPending && <Loader2 className="animate-spin" />}
              Connect number
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function CallDialog({ number, agents }: { number: PhoneNumberOut; agents: AgentOut[] }) {
  const { client } = useAuth()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [to, setTo] = useState('')
  const [agentId, setAgentId] = useState<string | null>(number.agent_id)
  const [consent, setConsent] = useState(false)
  const e164 = normalizeNumber(to)

  const call = useMutation({
    mutationFn: () =>
      client!.placeCall({
        from_number_id: number.id,
        agent_id: agentId!,
        to: e164,
        consent_confirmed: consent,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['calls'] })
      toast.success('Calling now. The call will appear in Calls.')
      setOpen(false)
      setTo('')
      setConsent(false)
    },
    onError: (e) => toast.error(describeError(e)),
  })

  const ready = E164.test(e164) && agentId != null && consent
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={<Button variant="outline" size="sm" aria-label={`Call someone from ${number.e164}`} />}
      >
        <PhoneOutgoing /> Call
      </DialogTrigger>
      <DialogContent>
        <form
          onSubmit={(ev) => {
            ev.preventDefault()
            if (ready) call.mutate()
          }}
          className="grid gap-4"
        >
          <DialogHeader>
            <DialogTitle>Place a call from {number.e164}</DialogTitle>
            <DialogDescription>The agent speaks as soon as they pick up.</DialogDescription>
          </DialogHeader>
          <Field label="Call this number" htmlFor="call-to" hint="International format, e.g. +14155550199.">
            <Input
              id="call-to"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              inputMode="tel"
              autoComplete="off"
              autoFocus
              required
            />
          </Field>
          <Field label="Agent" htmlFor="call-agent">
            <AgentSelect
              id="call-agent"
              agents={agents}
              value={agentId}
              onChange={setAgentId}
              nobodyLabel="Choose an agent"
            />
          </Field>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-1"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
            />
            <span>I have permission to call this person.</span>
          </label>
          <DialogFooter>
            <Button type="submit" disabled={!ready || call.isPending}>
              {call.isPending && <Loader2 className="animate-spin" />}
              Start call
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function NumberRow({ n, agents, canManage, canDial }: { n: PhoneNumberOut; agents: AgentOut[]; canManage: boolean; canDial: boolean }) {
  const { client } = useAuth()
  const queryClient = useQueryClient()
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['phone-numbers'] })
  const assign = useMutation({
    mutationFn: (agent_id: string | null) => client!.updateNumber(n.id, { agent_id }),
    onSuccess: refresh,
    onError: (e) => toast.error(describeError(e)),
  })
  const remove = useMutation({
    mutationFn: () => client!.disconnectNumber(n.id),
    onSuccess: () => {
      refresh()
      toast.success(`Disconnected ${n.e164}`)
    },
    onError: (e) => toast.error(describeError(e)),
  })
  // A saved assignment to an agent that is no longer live must still be visible, not blanked.
  const options =
    n.agent_id && !agents.some((a) => a.id === n.agent_id)
      ? [...agents, { id: n.agent_id, name: n.agent_name ?? 'Unpublished agent' } as AgentOut]
      : agents

  return (
    <TableRow>
      <TableCell className="font-medium tabular-nums">{n.e164}</TableCell>
      <TableCell>{n.label || <span className="text-muted-foreground">—</span>}</TableCell>
      <TableCell className="min-w-56">
        {canManage ? (
          <AgentSelect
            id={`assign-${n.id}`}
            agents={options}
            value={n.agent_id}
            disabled={assign.isPending}
            onChange={(id) => assign.mutate(id)}
          />
        ) : (
          (n.agent_name ?? <span className="text-muted-foreground">No one</span>)
        )}
      </TableCell>
      <TableCell className="text-right">
        <div className="flex justify-end gap-2">
          {canDial && <CallDialog number={n} agents={agents} />}
          {canManage && (
            <AlertDialog>
              <AlertDialogTrigger
                render={<Button variant="outline" size="icon" aria-label={`Disconnect ${n.e164}`} />}
              >
                <Trash2 />
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Disconnect {n.e164}?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Calls to this number stop reaching Voizy. The number stays in your Twilio
                    account.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction variant="destructive" onClick={() => remove.mutate()}>
                    Disconnect
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
        </div>
      </TableCell>
    </TableRow>
  )
}

export function PhonePage() {
  const { client, can } = useAuth()
  const numbers = useQuery({ queryKey: ['phone-numbers'], queryFn: () => client!.phoneNumbers(), enabled: !!client })
  const agentsQuery = useQuery({ queryKey: ['agents'], queryFn: () => client!.listAgents(), enabled: !!client })
  const agents = liveAgents(agentsQuery.data)
  const canManage = can('numbers:manage')
  const canDial = can('calls:place_outbound')

  return (
    <div className="mx-auto grid max-w-5xl gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Phone numbers</h1>
          <p className="text-muted-foreground text-sm">
            Numbers from your Twilio account that agents answer, and can call from.
          </p>
        </div>
        {canManage && <ConnectDialog agents={agents} />}
      </div>

      {numbers.isError && (
        <Alert variant="destructive" role="alert">
          <AlertDescription>{describeError(numbers.error)}</AlertDescription>
        </Alert>
      )}

      {numbers.isPending ? (
        <div className="grid gap-2" role="status" aria-label="Loading numbers">
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
        </div>
      ) : (numbers.data ?? []).length === 0 ? (
        <Card>
          <CardContent className="grid justify-items-center gap-2 py-10 text-center text-sm">
            <Phone className="text-muted-foreground size-6" />
            <p>No numbers connected yet.</p>
            <p className="text-muted-foreground max-w-md">
              Add your Twilio and LiveKit keys in{' '}
              <Link to="/settings" className="underline underline-offset-4">
                Settings
              </Link>
              , then connect a number to let an agent answer it.
            </p>
          </CardContent>
        </Card>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Number</TableHead>
              <TableHead>Label</TableHead>
              <TableHead>Answered by</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {numbers.data!.map((n) => (
              <NumberRow key={n.id} n={n} agents={agents} canManage={canManage} canDial={canDial} />
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
