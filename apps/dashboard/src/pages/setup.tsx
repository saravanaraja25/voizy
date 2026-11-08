import { Loader2, Rocket } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { describeError } from '@/api/client'
import { useAuth } from '@/auth/AuthContext'
import { AuthCard } from '@/components/auth-card'
import { Field } from '@/components/field'
import { PasswordFields, passwordProblem } from '@/components/password-fields'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export function SetupPage() {
  const { status, setup } = useAuth()
  const navigate = useNavigate()
  const [token, setToken] = useState('')
  const [workspace, setWorkspace] = useState('')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (status === 'loading') return null
  if (status === 'signedIn') return <Navigate to="/" replace />
  if (status === 'signedOut') return <Navigate to="/signin" replace />

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const problem = passwordProblem(password, confirm)
    if (problem) {
      setError(problem)
      return
    }
    setError(null)
    setBusy(true)
    try {
      await setup({
        setup_token: token.trim(),
        workspace_name: workspace.trim(),
        display_name: name.trim(),
        email: email.trim(),
        password,
      })
      navigate('/', { replace: true })
    } catch (err) {
      setError(describeError(err))
    } finally {
      setBusy(false)
    }
  }

  const ready = token.trim() && workspace.trim() && name.trim() && email.trim() && password

  return (
    <AuthCard
      title="Set up Voizy"
      description="Create your workspace and the first administrator account. This only happens once."
      onSubmit={onSubmit}
      footer={
        <Button type="submit" disabled={busy || !ready}>
          {busy ? <Loader2 className="animate-spin" /> : <Rocket />}
          {busy ? 'Setting up…' : 'Create workspace'}
        </Button>
      }
    >
      {error && (
        <Alert variant="destructive" role="alert">
          <AlertTitle>Could not finish setup</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <Field
        label="Setup token"
        htmlFor="setup-token"
        hint={
          <>
            Printed in the API server&apos;s log on first start, on the line that says{' '}
            <code className="bg-muted rounded px-1">FIRST-RUN SETUP</code>. It proves you control the
            server.
          </>
        }
      >
        <Input
          id="setup-token"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          spellCheck={false}
          autoComplete="off"
          autoFocus
          required
        />
      </Field>
      <Field label="Workspace name" htmlFor="workspace">
        <Input id="workspace" value={workspace} onChange={(e) => setWorkspace(e.target.value)} maxLength={100} required />
      </Field>
      <Field label="Your name" htmlFor="name">
        <Input id="name" value={name} onChange={(e) => setName(e.target.value)} maxLength={100} autoComplete="name" required />
      </Field>
      <Field label="Email" htmlFor="email">
        <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required />
      </Field>
      <PasswordFields idPrefix="setup" password={password} confirm={confirm} onPassword={setPassword} onConfirm={setConfirm} />
    </AuthCard>
  )
}
