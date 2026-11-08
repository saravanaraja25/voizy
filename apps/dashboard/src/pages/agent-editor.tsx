import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, Loader2, Rocket, Save } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { describeError, fieldErrors } from '@/api/client'
import type { AgentConfig, AgentOut, VersionOut, VersionSummary } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { PromptTab } from '@/components/editor/prompt-tab'
import { ToolsTab } from '@/components/editor/tools-tab'
import { TurnTab } from '@/components/editor/turn-tab'
import { VoiceTab } from '@/components/editor/voice-tab'
import { TestConsole } from '@/components/test-console'
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
import { Card, CardContent } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { isDirty } from '@/lib/config'

const TAB_PREFIXES: Record<string, string[]> = {
  prompt: ['system_prompt', 'languages', 'variables', 'name', 'default_language'],
  voice: ['stt', 'llm', 'tts', 'mode', 'realtime'],
  turn: ['turn'],
  tools: ['tools'],
}

function tabHasError(tab: string, errors: Record<string, string>): boolean {
  return Object.keys(errors).some((k) => TAB_PREFIXES[tab]!.some((p) => k === p || k.startsWith(`${p}.`)))
}

function ErrorDot({ show }: { show: boolean }) {
  return show ? (
    <>
      <span className="bg-destructive size-1.5 rounded-full" aria-hidden="true" />
      <span className="sr-only">(has errors)</span>
    </>
  ) : null
}

function EditorSkeleton({ name }: { name?: string }) {
  return (
    <div className="grid gap-6">
      {name ? (
        <h1 className="truncate text-2xl font-semibold tracking-tight">{name}</h1>
      ) : (
        <Skeleton className="h-8 w-56" />
      )}
    <Card>
      <CardContent className="grid gap-4 py-2" aria-busy="true" aria-label="Loading agent">
        <Skeleton className="h-9 w-72" />
        <Skeleton className="h-64 w-full" />
      </CardContent>
    </Card>
    </div>
  )
}

interface VersionEditorProps {
  agentId: string
  agent: AgentOut
  versions: VersionSummary[]
  selected: number
  initial: AgentConfig
  onSelect: (version: number) => void
  onSaved: (version: VersionOut) => void
}

/**
 * Owns the editable draft for ONE version. The page remounts it (via key) when the version
 * changes, so there is never a stale draft to synchronise and no effect-driven state copying.
 */
function VersionEditor({ agentId, agent, versions, selected, initial, onSelect, onSaved }: VersionEditorProps) {
  const { client, can } = useAuth()
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<AgentConfig>(() => structuredClone(initial))
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saveError, setSaveError] = useState<string | null>(null)
  const [invalid, setInvalid] = useState<Set<string>>(new Set())
  const [pendingSwitch, setPendingSwitch] = useState<number | null>(null)
  const [confirmPublish, setConfirmPublish] = useState(false)

  const catalog = useQuery({
    queryKey: ['catalog'],
    queryFn: () => client!.catalog(),
    staleTime: 600_000,
  })

  const dirty = isDirty(initial, draft)

  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  const setValidity = useCallback((key: string, valid: boolean) => {
    setInvalid((prev) => {
      if (valid === !prev.has(key)) return prev
      const next = new Set(prev)
      if (valid) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  const save = useMutation({
    mutationFn: (config: AgentConfig) => client!.createVersion(agentId, config),
    onSuccess: (v) => {
      void queryClient.invalidateQueries({ queryKey: ['versions', agentId] })
      void queryClient.invalidateQueries({ queryKey: ['agents'] })
      toast.success(`Saved as version ${v.version}`)
      onSaved(v)
    },
    onError: (e) => {
      setErrors(fieldErrors(e))
      setSaveError(describeError(e))
    },
  })

  const publish = useMutation({
    mutationFn: (v: number) => client!.publish(agentId, v),
    onSuccess: (a) => {
      queryClient.setQueryData(['agent', agentId], a)
      void queryClient.invalidateQueries({ queryKey: ['versions', agentId] })
      void queryClient.invalidateQueries({ queryKey: ['agents'] })
      toast.success(`Version ${a.published_version} is live`)
    },
    onError: (e) => toast.error(describeError(e)),
  })

  const summary = useMemo(() => versions.find((v) => v.version === selected), [versions, selected])

  function requestSwitch(v: number) {
    if (v === selected) return
    if (dirty) setPendingSwitch(v)
    else onSelect(v)
  }

  const canEdit = can('agents:edit')
  const isLive = agent.published_version === selected
  const blocked = invalid.size > 0
  const testBlock = !can('agents:test')
    ? "You don't have permission to start test calls."
    : dirty
      ? 'Save your changes as a new version to test them.'
      : undefined
  const common = { config: draft, onChange: setDraft, errors, disabled: !canEdit }

  return (
    <div className="mx-auto grid max-w-7xl gap-6">
      <div className="grid gap-3">
        <Button variant="ghost" size="sm" className="-ml-2 w-fit" render={<Link to="/" />} nativeButton={false}>
          <ChevronLeft /> Agents
        </Button>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="min-w-0 truncate text-2xl font-semibold tracking-tight">{agent.name}</h1>
          <div className="flex flex-wrap items-center gap-2">
            <Select
              value={String(selected)}
              items={versions.map((v) => ({ value: String(v.version), label: `Version ${v.version}` }))}
              onValueChange={(v) => v && requestSwitch(Number(v))}
            >
              <SelectTrigger className="w-44" aria-label="Version">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {versions.map((v) => (
                  <SelectItem key={v.version} value={String(v.version)}>
                    Version {v.version}
                    {agent.published_version === v.version ? ' · live' : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {isLive ? (
              <Badge>Live</Badge>
            ) : summary?.is_published ? (
              <Badge variant="outline">Published earlier</Badge>
            ) : (
              <Badge variant="secondary">Draft</Badge>
            )}
            {dirty && <Badge variant="outline">Unsaved changes</Badge>}
            {canEdit && (
              <Button
                onClick={() => save.mutate(draft)}
                disabled={!dirty || save.isPending || blocked}
                title={blocked ? 'Fix the invalid tool schema first' : undefined}
              >
                {save.isPending ? <Loader2 className="animate-spin" /> : <Save />} Save as new version
              </Button>
            )}
            {can('agents:publish') && (
              <Button
                variant="outline"
                onClick={() => setConfirmPublish(true)}
                disabled={dirty || isLive || publish.isPending}
              >
                {publish.isPending ? <Loader2 className="animate-spin" /> : <Rocket />} Publish
              </Button>
            )}
          </div>
        </div>
      </div>

      {saveError && (
        <Alert variant="destructive" role="alert">
          <AlertTitle>Could not save</AlertTitle>
          <AlertDescription>{saveError}</AlertDescription>
        </Alert>
      )}
      {!canEdit && (
        <Alert>
          <AlertDescription>You have read-only access to this agent.</AlertDescription>
        </Alert>
      )}

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_26rem]">
        <Card>
          <CardContent>
            <Tabs defaultValue="prompt">
              <TabsList className="mb-6 flex-wrap">
                <TabsTrigger value="prompt">Prompt <ErrorDot show={tabHasError('prompt', errors)} /></TabsTrigger>
                <TabsTrigger value="voice">Voice &amp; models <ErrorDot show={tabHasError('voice', errors)} /></TabsTrigger>
                <TabsTrigger value="turn">Turn-taking <ErrorDot show={tabHasError('turn', errors)} /></TabsTrigger>
                <TabsTrigger value="tools">Tools <ErrorDot show={tabHasError('tools', errors)} /></TabsTrigger>
              </TabsList>
              <TabsContent keepMounted value="prompt"><PromptTab {...common} /></TabsContent>
              <TabsContent keepMounted value="voice"><VoiceTab {...common} catalog={catalog.data} /></TabsContent>
              <TabsContent keepMounted value="turn"><TurnTab {...common} /></TabsContent>
              <TabsContent keepMounted value="tools"><ToolsTab {...common} onValidity={setValidity} /></TabsContent>
            </Tabs>
          </CardContent>
        </Card>

        <div className="xl:sticky xl:top-20">
          <TestConsole agentId={agentId} version={selected} disabledReason={testBlock} />
        </div>
      </div>

      <AlertDialog open={pendingSwitch != null} onOpenChange={(o) => !o && setPendingSwitch(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard unsaved changes?</AlertDialogTitle>
            <AlertDialogDescription>
              Switching to version {pendingSwitch} will discard the edits you have not saved.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep editing</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (pendingSwitch != null) onSelect(pendingSwitch)
                setPendingSwitch(null)
              }}
            >
              Discard and switch
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={confirmPublish} onOpenChange={setConfirmPublish}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Publish version {selected}?</AlertDialogTitle>
            <AlertDialogDescription>
              New calls to this agent will use version {selected} immediately. Calls already in
              progress are not affected.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => publish.mutate(selected)}>Publish</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

export function AgentEditorPage() {
  const { id = '' } = useParams()
  const { client } = useAuth()
  const queryClient = useQueryClient()
  const [picked, setPicked] = useState<number | null>(null)

  const agent = useQuery({ queryKey: ['agent', id], queryFn: () => client!.getAgent(id), enabled: !!client })
  const versions = useQuery({ queryKey: ['versions', id], queryFn: () => client!.listVersions(id), enabled: !!client })

  // Derived, not synced: the live version if there is one, otherwise the newest.
  const selected = picked ?? agent.data?.published_version ?? versions.data?.[0]?.version ?? null

  const version = useQuery({
    queryKey: ['version', id, selected],
    queryFn: () => client!.getVersion(id, selected!),
    enabled: !!client && selected != null,
  })

  if (agent.isError || versions.isError) {
    return (
      <Alert variant="destructive" className="mx-auto max-w-2xl">
        <AlertTitle>Could not open this agent</AlertTitle>
        <AlertDescription>{describeError(agent.error ?? versions.error)}</AlertDescription>
      </Alert>
    )
  }
  if (!agent.data || !versions.data || selected == null || !version.data) {
    return (
      <div className="mx-auto max-w-7xl">
        <EditorSkeleton name={agent.data?.name} />
      </div>
    )
  }

  return (
    <VersionEditor
      key={`${id}:${selected}`}
      agentId={id}
      agent={agent.data}
      versions={versions.data}
      selected={selected}
      initial={version.data.config}
      onSelect={setPicked}
      onSaved={(v) => {
        queryClient.setQueryData(['version', id, v.version], v)
        setPicked(v.version)
      }}
    />
  )
}
