import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { createClient } from '../api/client'
import type { Client } from '../api/client'
import type { MeOut, SetupRequest } from '../api/types'
import { getCsrf, setCsrf } from './csrf'

type Status = 'loading' | 'signedOut' | 'needsSetup' | 'signedIn'

interface AuthState {
  status: Status
  me: MeOut | null
  client: Client
  signIn: (email: string, password: string) => Promise<void>
  setup: (request: SetupRequest) => Promise<void>
  acceptInvite: (token: string, displayName: string, password: string) => Promise<void>
  signOut: () => Promise<void>
  can: (permission: string) => boolean
}

const Ctx = createContext<AuthState | null>(null)

/**
 * Session state. The session itself lives in an HttpOnly cookie the page can never read; all
 * this holds in memory is who you are and the CSRF token that must accompany every write.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<Status>('loading')
  const [me, setMe] = useState<MeOut | null>(null)

  const reset = useCallback(
    (next: Status) => {
      setCsrf(null)
      queryClient.clear() // never show one session's data to the next
      setMe(null)
      setStatus(next)
    },
    [queryClient],
  )

  const client = useMemo(
    () =>
      createClient({
        baseUrl: import.meta.env.VITE_API_URL ?? '',
        getCsrf,
        onUnauthorized: () => reset('signedOut'),
      }),
    [reset],
  )

  const adopt = useCallback(
    (who: MeOut) => {
      queryClient.clear()
      setCsrf(who.csrf_token ?? null)
      setMe(who)
      setStatus('signedIn')
    },
    [queryClient],
  )

  // On load: am I already signed in? If not, does this instance still need first-run setup?
  // State is only set from promise callbacks; `cancelled` makes StrictMode's double effect harmless.
  useEffect(() => {
    let cancelled = false
    client
      .me()
      .then((who) => {
        if (!cancelled) adopt(who)
      })
      .catch(() =>
        client
          .setupStatus()
          .then((s) => {
            if (!cancelled) setStatus(s.needs_setup ? 'needsSetup' : 'signedOut')
          })
          .catch(() => {
            if (!cancelled) setStatus('signedOut')
          }),
      )
    return () => {
      cancelled = true
    }
  }, [client, adopt])

  const value = useMemo<AuthState>(
    () => ({
      status,
      me,
      client,
      signIn: async (email, password) => adopt(await client.login(email, password)),
      setup: async (request) => adopt(await client.setup(request)),
      acceptInvite: async (token, displayName, password) =>
        adopt(await client.acceptInvite(token, displayName, password)),
      signOut: async () => {
        await client.logout().catch(() => undefined)
        reset('signedOut')
      },
      can: (p) => !!me?.permissions.includes(p as never),
    }),
    [status, me, client, adopt, reset],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth(): AuthState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAuth must be used inside AuthProvider')
  return v
}
