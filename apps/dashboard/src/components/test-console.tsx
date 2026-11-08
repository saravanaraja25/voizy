import { Mic, MicOff, Phone, PhoneOff, Loader2, Info } from 'lucide-react'
import { Room, RoomEvent, Track } from 'livekit-client'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { describeError } from '@/api/client'
import { useAuth } from '@/auth/AuthContext'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { breakdown, isTurnLatency, TARGET_MS } from '@/lib/latency'
import type { TurnLatency } from '@/lib/latency'
import { cn } from '@/lib/utils'

type Phase = 'idle' | 'connecting' | 'live' | 'ended'
interface Line {
  key: string
  role: 'user' | 'agent'
  text: string
}

const STATE_LABEL: Record<string, string> = {
  initializing: 'Starting…',
  listening: 'Listening',
  thinking: 'Thinking',
  speaking: 'Speaking',
}

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b)
  return s[Math.floor((s.length - 1) / 2)] ?? 0
}

function LatencyChart({ turns }: { turns: TurnLatency[] }) {
  if (turns.length === 0) {
    return <p className="text-muted-foreground text-sm">Latency per turn appears here once you speak.</p>
  }
  const rows = turns.slice(-6).map((t) => ({ id: t.id, ...breakdown(t.ms) }))
  const scale = Math.max(TARGET_MS, ...rows.map((r) => r.total))
  const med = median(turns.map((t) => breakdown(t.ms).total))
  return (
    <div className="grid gap-3">
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-medium">Response time</span>
        <span className={cn('text-sm tabular-nums', med > TARGET_MS ? 'text-destructive' : 'text-muted-foreground')}>
          median {med} ms · target {TARGET_MS} ms
        </span>
      </div>
      <ul className="grid gap-2" aria-label="Latency by turn">
        {rows.map((r) => (
          <li key={r.id} className="grid gap-1">
            <div className="flex h-3 w-full overflow-hidden rounded-full bg-muted" role="img"
              aria-label={`Turn ${r.id}: ${r.total} milliseconds. ${r.segments.map((s) => `${s.label} ${s.ms}`).join(', ')}`}>
              {r.segments.map((s) => (
                <div key={s.key} className={s.className} style={{ width: `${(s.ms / scale) * 100}%` }} title={`${s.label}: ${s.ms} ms`} />
              ))}
            </div>
            <div className="text-muted-foreground flex justify-between text-xs tabular-nums">
              <span>Turn {r.id}</span>
              <span>{r.total} ms</span>
            </div>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {[
          ['bg-sky-500', 'Turn detection'],
          ['bg-violet-500', 'LLM'],
          ['bg-amber-500', 'Tools'],
          ['bg-emerald-500', 'Speech'],
        ].map(([c, l]) => (
          <span key={l} className="flex items-center gap-1.5">
            <span className={cn('size-2.5 rounded-sm', c)} /> {l}
          </span>
        ))}
      </div>
    </div>
  )
}

export function TestConsole({
  agentId,
  version,
  disabledReason,
}: {
  agentId: string
  version: number
  disabledReason?: string
}) {
  const { client, can } = useAuth()
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState<string | null>(null)
  const [lines, setLines] = useState<Line[]>([])
  const [turns, setTurns] = useState<TurnLatency[]>([])
  const [agentState, setAgentState] = useState<string | null>(null)
  const [muted, setMuted] = useState(false)
  const roomRef = useRef<Room | null>(null)
  const audioRef = useRef<HTMLDivElement>(null)
  const logRef = useRef<HTMLDivElement>(null)
  const turnId = useRef(0)

  const stop = useCallback(async () => {
    const room = roomRef.current
    roomRef.current = null
    if (room) await room.disconnect()
    audioRef.current?.replaceChildren()
    setAgentState(null)
    setPhase((p) => (p === 'idle' ? p : 'ended'))
  }, [])

  useEffect(() => () => void stop(), [stop])
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight })
  }, [lines])

  async function start() {
    if (!client) return
    setError(null)
    setLines([])
    setTurns([])
    setMuted(false)
    turnId.current = 0
    setPhase('connecting')
    try {
      const session = await client.testSession(agentId, version)
      const room = new Room()
      roomRef.current = room

      room.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind === Track.Kind.Audio) audioRef.current?.appendChild(track.attach())
      })
      room.on(RoomEvent.TrackUnsubscribed, (track) => track.detach().forEach((el) => el.remove()))
      room.on(RoomEvent.DataReceived, (payload, _p, _k, topic) => {
        if (topic !== 'voizy.latency') return
        try {
          const msg: unknown = JSON.parse(new TextDecoder().decode(payload))
          if (isTurnLatency(msg)) {
            const id = ++turnId.current // outside the updater: StrictMode runs updaters twice
            setTurns((t) => [...t, { id, ms: msg.ms }])
          }
        } catch {
          /* ignore malformed telemetry */
        }
      })
      room.on(RoomEvent.ParticipantAttributesChanged, (changed, participant) => {
        if (!participant.isLocal && 'lk.agent.state' in changed) {
          setAgentState(participant.attributes['lk.agent.state'] ?? null)
        }
      })
      room.on(RoomEvent.Disconnected, () => {
        if (roomRef.current === room) void stop()
      })
      room.registerTextStreamHandler('lk.transcription', async (reader, info) => {
        const key = reader.info.attributes?.['lk.segment_id'] ?? reader.info.id
        const role = info.identity === room.localParticipant.identity ? 'user' : 'agent'
        let text = ''
        for await (const chunk of reader) {
          text += chunk
          setLines((prev) => {
            const next = prev.filter((l) => l.key !== key)
            const existing = prev.findIndex((l) => l.key === key)
            const line: Line = { key, role, text }
            if (existing === -1) return [...prev, line]
            next.splice(existing, 0, line)
            return next
          })
        }
      })

      await room.connect(session.url, session.token)
      await room.startAudio()
      await room.localParticipant.setMicrophoneEnabled(true)
      setPhase('live')
    } catch (e) {
      await stop()
      setPhase('idle')
      const name = e instanceof Error ? e.name : ''
      setError(
        name === 'NotAllowedError' || name === 'NotFoundError'
          ? 'Microphone access was blocked. Allow the microphone for this site and try again.'
          : describeError(e),
      )
    }
  }

  async function toggleMute() {
    const room = roomRef.current
    if (!room) return
    const next = !muted
    await room.localParticipant.setMicrophoneEnabled(!next)
    setMuted(next)
  }

  const live = phase === 'live'
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <CardTitle>Test call</CardTitle>
          {live && agentState && <Badge variant="secondary" aria-live="polite">{STATE_LABEL[agentState] ?? agentState}</Badge>}
          {phase === 'connecting' && <Badge variant="secondary">Connecting…</Badge>}
        </div>
        <CardDescription>
          Talk to version {version} from your browser. Use headphones to avoid echo.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {disabledReason && (
          <Alert>
            <Info />
            <AlertDescription>{disabledReason}</AlertDescription>
          </Alert>
        )}
        {error && (
          <Alert variant="destructive" role="alert">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {phase === 'ended' && can('calls:read') && (
          <p className="text-muted-foreground text-sm">
            Call ended. <Link className="underline underline-offset-4" to={`/calls?agent_id=${agentId}`}>View it in Calls</Link>
          </p>
        )}

        <div className="flex gap-2">
          {!live ? (
            <Button onClick={() => void start()} disabled={!!disabledReason || phase === 'connecting'} className="flex-1">
              {phase === 'connecting' ? <Loader2 className="animate-spin" /> : <Phone />}
              {phase === 'ended' ? 'Call again' : 'Start call'}
            </Button>
          ) : (
            <>
              <Button variant="destructive" onClick={() => void stop()} className="flex-1">
                <PhoneOff /> End call
              </Button>
              <Button variant="outline" size="icon" onClick={() => void toggleMute()} aria-pressed={muted} aria-label={muted ? 'Unmute microphone' : 'Mute microphone'}>
                {muted ? <MicOff /> : <Mic />}
              </Button>
            </>
          )}
        </div>

        <div
          ref={logRef}
          className="bg-muted/40 max-h-72 min-h-32 overflow-y-auto rounded-lg border p-3"
          role="log"
          aria-live="polite"
          aria-label="Call transcript"
        >
          {lines.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              {live ? 'Say something…' : 'The transcript appears here during the call.'}
            </p>
          ) : (
            <ul className="grid gap-2">
              {lines.map((l) => (
                <li key={l.key} className={cn('flex', l.role === 'user' ? 'justify-end' : 'justify-start')}>
                  <span
                    className={cn(
                      'max-w-[85%] rounded-2xl px-3 py-1.5 text-sm',
                      l.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-card border',
                    )}
                  >
                    <span className="sr-only">{l.role === 'user' ? 'You: ' : 'Agent: '}</span>
                    {l.text}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <LatencyChart turns={turns} />
        <div ref={audioRef} className="hidden" aria-hidden="true" />
      </CardContent>
    </Card>
  )
}
