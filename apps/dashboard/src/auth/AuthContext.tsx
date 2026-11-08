import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { createClient, describeError } from '../api/client'
import type { Client } from '../api/client'
import type { MeOut } from '../api/types'
import { clearSession, loadSession, normalizeBaseUrl, saveSession } from './session'

interface AuthState {
  status: 'loading' | 'signedOut' | 'signedIn'
  me: MeOut | null
  client: Client | null
  signIn: (baseUrl: string, key: string) => Promise<void>
  signOut: () => void
  can: (permission: string) => boolean
}

const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  // Decide synchronously whether there is a session to restore, so no effect has to set state.
  const [status, setStatus] = useState<AuthState['status']>(() =>
    loadSession() ? 'loading' : 'signedOut',
  )
  const [me, setMe] = useState<MeOut | null>(null)
  const [client, setClient] = useState<Client | null>(null)
  const queryClient = useQueryClient()

  const signOut = useCallback(() => {
    queryClient.clear() // never show one session's data to the next
    clearSession()
    setMe(null)
    setClient(null)
    setStatus('signedOut')
  }, [queryClient])

  const connect = useCallback(
    async (baseUrl: string, key: string) => {
      const c = createClient(baseUrl, key, signOut)
      const who = await c.me()
      setClient(c)
      setMe(who)
      setStatus('signedIn')
    },
    [signOut],
  )

  const signIn = useCallback(
    async (rawUrl: string, key: string) => {
      const baseUrl = normalizeBaseUrl(rawUrl)
      if (!baseUrl) throw new Error('Enter a valid API URL (https, or http for localhost).')
      try {
        queryClient.clear()
        await connect(baseUrl, key.trim())
      } catch (e) {
        throw new Error(
          e instanceof Error && e.message.includes('Failed to fetch')
            ? 'Could not reach the API. Check the URL and that CORS allows this origin.'
            : describeError(e),
          { cause: e },
        )
      }
      saveSession({ baseUrl, key: key.trim() })
    },
    [connect, queryClient],
  )

  // Restore a session that survived a page refresh. State is only set from the promise callbacks,
  // and `cancelled` makes StrictMode's double-invoked effect harmless.
  useEffect(() => {
    const stored = loadSession()
    if (!stored) return
    let cancelled = false
    const c = createClient(stored.baseUrl, stored.key, signOut)
    c.me()
      .then((who) => {
        if (cancelled) return
        setClient(c)
        setMe(who)
        setStatus('signedIn')
      })
      .catch(() => {
        if (!cancelled) signOut()
      })
    return () => {
      cancelled = true
    }
  }, [signOut])

  const value = useMemo<AuthState>(
    () => ({
      status,
      me,
      client,
      signIn,
      signOut,
      can: (p) => !!me?.permissions.includes(p as never),
    }),
    [status, me, client, signIn, signOut],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth(): AuthState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAuth must be used inside AuthProvider')
  return v
}
