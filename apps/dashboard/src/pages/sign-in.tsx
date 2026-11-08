import { AudioLines, KeyRound, Loader2 } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '@/auth/AuthContext'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const DEFAULT_API = import.meta.env.VITE_API_URL ?? 'http://localhost:8010'

export function SignInPage() {
  const { status, signIn } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [baseUrl, setBaseUrl] = useState(DEFAULT_API)
  const [key, setKey] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (status === 'signedIn') {
    return <Navigate to={(location.state as { from?: string } | null)?.from ?? '/'} replace />
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await signIn(baseUrl, key)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not sign in.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="bg-muted/40 flex min-h-svh items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <form onSubmit={onSubmit} noValidate>
          <CardHeader>
            <div className="bg-primary text-primary-foreground mb-2 flex size-10 items-center justify-center rounded-lg">
              <AudioLines className="size-5" />
            </div>
            <CardTitle className="text-xl" role="heading" aria-level={1}>
              Sign in to Voizy
            </CardTitle>
            <CardDescription>
              Use an API key for your workspace. Create the first one with{' '}
              <code className="bg-muted rounded px-1 py-0.5 text-xs">voizy-admin bootstrap</code>.
            </CardDescription>
          </CardHeader>
          <CardContent className="mt-4 grid gap-4">
            {error && (
              <Alert variant="destructive" role="alert">
                <AlertTitle>Could not sign in</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <div className="grid gap-2">
              <Label htmlFor="api-url">API URL</Label>
              <Input
                id="api-url"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                autoComplete="url"
                spellCheck={false}
                required
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="api-key">API key</Label>
              <Input
                id="api-key"
                type="password"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder="vz_…"
                autoComplete="off"
                spellCheck={false}
                required
              />
            </div>
          </CardContent>
          <CardFooter className="mt-6 flex-col items-stretch gap-3">
            <Button type="submit" disabled={busy || key.trim() === ''}>
              {busy ? <Loader2 className="animate-spin" /> : <KeyRound />}
              {busy ? 'Signing in…' : 'Sign in'}
            </Button>
            <p className="text-muted-foreground text-xs">
              The key is kept in this tab only and is cleared when you close it or sign out.
            </p>
          </CardFooter>
        </form>
      </Card>
    </div>
  )
}
