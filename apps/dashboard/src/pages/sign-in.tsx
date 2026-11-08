import { Loader2, LogIn } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { describeError } from '@/api/client'
import { useAuth } from '@/auth/AuthContext'
import { AuthCard } from '@/components/auth-card'
import { Field } from '@/components/field'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export function SignInPage() {
  const { status, signIn } = useAuth()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (status === 'loading') return null
  if (status === 'needsSetup') return <Navigate to="/setup" replace />
  if (status === 'signedIn') {
    return <Navigate to={(location.state as { from?: string } | null)?.from ?? '/'} replace />
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      // Navigation happens declaratively once the session is established (see the redirect
      // above), so it returns you to the page you were sent away from, deterministically.
      await signIn(email.trim(), password)
    } catch (err) {
      setError(describeError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthCard
      title="Sign in to Voizy"
      description="Use the email and password for your workspace account."
      onSubmit={onSubmit}
      footer={
        <Button type="submit" disabled={busy || !email.trim() || !password}>
          {busy ? <Loader2 className="animate-spin" /> : <LogIn />}
          {busy ? 'Signing in…' : 'Sign in'}
        </Button>
      }
    >
      {error && (
        <Alert variant="destructive" role="alert">
          <AlertTitle>Could not sign in</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <Field label="Email" htmlFor="email">
        <Input
          id="email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="username"
          autoFocus
          required
        />
      </Field>
      <Field label="Password" htmlFor="password">
        <Input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          required
        />
      </Field>
    </AuthCard>
  )
}
