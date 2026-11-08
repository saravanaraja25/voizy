import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, Loader2, Plus, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { describeError } from '@/api/client'
import type { AgentOut } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
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
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { newAgentConfig } from '@/lib/config'

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' })

function StatusBadge({ agent }: { agent: AgentOut }) {
  if (agent.archived) return <Badge variant="outline">Archived</Badge>
  if (agent.published_version != null) return <Badge>Live · v{agent.published_version}</Badge>
  return <Badge variant="secondary">Draft</Badge>
}

function NewAgentDialog() {
  const { client } = useAuth()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')

  const create = useMutation({
    mutationFn: async (agentName: string) => {
      if (!client) throw new Error('Not signed in')
      const catalog = await client.catalog().catch(() => undefined)
      return client.createAgent(agentName, newAgentConfig(agentName, catalog))
    },
    onSuccess: (agent) => {
      void queryClient.invalidateQueries({ queryKey: ['agents'] })
      toast.success(`Created “${agent.name}”`)
      setOpen(false)
      setName('')
      navigate(`/agents/${agent.id}`)
    },
    onError: (e) => toast.error(describeError(e)),
  })

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmed = name.trim()
    if (trimmed) create.mutate(trimmed)
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button />}>
        <Plus /> New agent
      </DialogTrigger>
      <DialogContent>
        <form onSubmit={onSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Create an agent</DialogTitle>
            <DialogDescription>
              Start from a friendly receptionist and change anything: prompt, voice, tools and
              turn-taking.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <Label htmlFor="agent-name">Name</Label>
            <Input
              id="agent-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Front desk"
              maxLength={100}
              autoFocus
              required
            />
          </div>
          <DialogFooter>
            <Button type="submit" disabled={create.isPending || name.trim() === ''}>
              {create.isPending && <Loader2 className="animate-spin" />}
              Create agent
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function AgentsPage() {
  const { client, can } = useAuth()
  const agents = useQuery({
    queryKey: ['agents'],
    queryFn: () => client!.listAgents(),
    enabled: !!client,
  })

  return (
    <div className="mx-auto grid max-w-5xl gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Agents</h1>
          <p className="text-muted-foreground text-sm">
            Each agent is a versioned configuration. Publish a version to make it live.
          </p>
        </div>
        {can('agents:create') && <NewAgentDialog />}
      </div>

      {agents.isError && (
        <Alert variant="destructive">
          <AlertTitle>Could not load agents</AlertTitle>
          <AlertDescription className="flex items-center justify-between gap-3">
            <span>{describeError(agents.error)}</span>
            <Button variant="outline" size="sm" onClick={() => void agents.refetch()}>
              <RefreshCw /> Retry
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {agents.isPending && (
        <Card>
          <CardContent className="grid gap-3 py-2" aria-busy="true" aria-label="Loading agents">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </CardContent>
        </Card>
      )}

      {agents.data && agents.data.length === 0 && (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center gap-3 py-14 text-center">
            <div className="bg-muted flex size-12 items-center justify-center rounded-full">
              <Bot className="text-muted-foreground size-6" />
            </div>
            <h2 className="text-lg font-medium">No agents yet</h2>
            <p className="text-muted-foreground max-w-sm text-sm">
              Create your first voice agent, tune it, then try it with a live test call right from
              this page.
            </p>
            {can('agents:create') && <NewAgentDialog />}
          </CardContent>
        </Card>
      )}

      {agents.data && agents.data.length > 0 && (
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="hidden sm:table-cell">Created</TableHead>
                <TableHead className="w-24 text-right">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {agents.data.map((agent) => (
                <TableRow key={agent.id}>
                  <TableCell className="font-medium">
                    <Link to={`/agents/${agent.id}`} className="hover:underline">
                      {agent.name}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <StatusBadge agent={agent} />
                  </TableCell>
                  <TableCell className="text-muted-foreground hidden sm:table-cell">
                    {dateFormat.format(new Date(agent.created_at))}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button variant="ghost" size="sm" render={<Link to={`/agents/${agent.id}`} />} nativeButton={false}>
                      Open
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  )
}
