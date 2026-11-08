import { useQuery } from '@tanstack/react-query'
import { Loader2, UserPlus } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom'
import { describeError } from '@/api/client'
import { useAuth } from '@/auth/AuthContext'
import { AuthCard } from '@/components/auth-card'
import { Field } from '@/components/field'
import { PasswordFields, passwordProblem } from '@/components/password-fields'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export function InvitePage() {
  const { token = '' } = useParams()
  const { client, status, acceptInvite } = useAuth()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const preview = useQuery({
    queryKey: ['invite', token],
    queryFn: () => client.previewInvite(token),
    enabled: status !== 'loading' && status !== 'signedIn',
    retry: false,
  })

  if (status === 'signedIn') return <Navigate to="/" replace />
  if (status === 'loading' || preview.isPending) {
    return (
      <div className="flex min-h-svh items-center justify-center" role="status" aria-label="Loading invitation">
        <Loader2 className="text-muted-foreground size-6 animate-spin" />
      </div>
    )
  }
  if (preview.isError) {
    return (
      <AuthCard
        title="Invitation not valid"
        description="This link has expired, was already used, or was withdrawn. Ask the person who invited you for a new one."
        footer={<Button render={<Link to="/signin" />} nativeButton={false} variant="outline">Go to sign in</Button>}
      >
        <span className="sr-only">{describeError(preview.error)}</span>
      </AuthCard>
    )
  }

  const invite = preview.data

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
      await acceptInvite(token, name.trim(), password)
      navigate('/', { replace: true })
    } catch (err) {
      setError(describeError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthCard
      title={`Join ${invite.workspace_name}`}
      description={`You were invited as ${invite.role_name}. Choose a password to create your account.`}
      onSubmit={onSubmit}
      footer={
        <Button type="submit" disabled={busy || !name.trim() || !password}>
          {busy ? <Loader2 className="animate-spin" /> : <UserPlus />}
          {busy ? 'Creating account…' : 'Create account'}
        </Button>
      }
    >
      {error && (
        <Alert variant="destructive" role="alert">
          <AlertTitle>Could not create the account</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <Field label="Email" htmlFor="invite-email" hint="The invitation is tied to this address.">
        <Input id="invite-email" value={invite.email} readOnly />
      </Field>
      <Field label="Your name" htmlFor="invite-name">
        <Input id="invite-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={100} autoComplete="name" autoFocus required />
      </Field>
      <PasswordFields idPrefix="invite" password={password} confirm={confirm} onPassword={setPassword} onConfirm={setConfirm} />
    </AuthCard>
  )
}
