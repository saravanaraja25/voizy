import { useMutation } from '@tanstack/react-query'
import { KeyRound, Loader2 } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { toast } from 'sonner'
import { describeError } from '@/api/client'
import { useAuth } from '@/auth/AuthContext'
import { Field } from '@/components/field'
import { PasswordFields, passwordProblem } from '@/components/password-fields'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'

export function AccountPage() {
  const { client, me } = useAuth()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)

  const change = useMutation({
    mutationFn: () => client.changePassword(current, next),
    onSuccess: () => {
      setCurrent('')
      setNext('')
      setConfirm('')
      setError(null)
      toast.success('Password changed. Your other sessions were signed out.')
    },
    onError: (e) => setError(describeError(e)),
  })

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    const problem = passwordProblem(next, confirm)
    if (problem) {
      setError(problem)
      return
    }
    setError(null)
    change.mutate()
  }

  return (
    <div className="mx-auto grid max-w-2xl gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Account</h1>
        <p className="text-muted-foreground text-sm">Your sign-in details for {me?.workspace_name}.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Profile</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          <Field label="Name" htmlFor="profile-name">
            <Input id="profile-name" value={me?.display_name ?? ''} readOnly />
          </Field>
          <Field label="Email" htmlFor="profile-email">
            <Input id="profile-email" value={me?.email ?? ''} readOnly />
          </Field>
        </CardContent>
      </Card>

      <Card>
        <form onSubmit={onSubmit} noValidate>
          <CardHeader>
            <CardTitle>Change password</CardTitle>
            <CardDescription>Changing it signs you out everywhere else.</CardDescription>
          </CardHeader>
          <CardContent className="mt-4 grid gap-4">
            {error && (
              <Alert variant="destructive" role="alert">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <Field label="Current password" htmlFor="current-password">
              <Input id="current-password" type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required />
            </Field>
            <PasswordFields idPrefix="account" label="New password" password={next} confirm={confirm} onPassword={setNext} onConfirm={setConfirm} />
          </CardContent>
          <CardFooter className="mt-6">
            <Button type="submit" disabled={change.isPending || !current || !next}>
              {change.isPending ? <Loader2 className="animate-spin" /> : <KeyRound />} Change password
            </Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  )
}
