import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, Loader2, Mail, Trash2, UserPlus } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { toast } from 'sonner'
import { describeError } from '@/api/client'
import type { AssignableRole, InviteCreated, MemberOut } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { Field } from '@/components/field'
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
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' })
const dateTimeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })

export function inviteLink(token: string): string {
  return `${window.location.origin}/invite/${token}`
}

function InviteDialog({ roles }: { roles: AssignableRole[] }) {
  const { client } = useAuth()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [roleId, setRoleId] = useState('')
  const [created, setCreated] = useState<InviteCreated | null>(null)
  const [copied, setCopied] = useState(false)

  const invite = useMutation({
    mutationFn: () => client.createInvite(email.trim(), roleId),
    onSuccess: (inv) => {
      setCreated(inv)
      void queryClient.invalidateQueries({ queryKey: ['invites'] })
    },
    onError: (e) => toast.error(describeError(e)),
  })

  function reset(next: boolean) {
    setOpen(next)
    if (!next) {
      setEmail('')
      setRoleId('')
      setCreated(null)
      setCopied(false)
    }
  }

  async function copy(link: string) {
    try {
      await navigator.clipboard.writeText(link)
      setCopied(true)
    } catch {
      toast.error('Could not copy. Select the link and copy it manually.')
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (email.trim() && roleId) invite.mutate()
  }

  const items = roles.map((r) => ({ value: r.id, label: r.name }))
  return (
    <Dialog open={open} onOpenChange={reset}>
      <DialogTrigger render={<Button />}>
        <UserPlus /> Invite someone
      </DialogTrigger>
      <DialogContent>
        {created ? (
          <div className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Invitation ready</DialogTitle>
              <DialogDescription>
                Send this link to {created.email}. It works once, expires in 7 days, and is shown
                only now. No email is sent automatically.
              </DialogDescription>
            </DialogHeader>
            <div className="flex gap-2">
              <Input readOnly value={inviteLink(created.token)} aria-label="Invitation link" onFocus={(e) => e.currentTarget.select()} />
              <Button type="button" variant="outline" onClick={() => void copy(inviteLink(created.token))}>
                {copied ? <Check /> : <Copy />} {copied ? 'Copied' : 'Copy'}
              </Button>
            </div>
            <DialogFooter>
              <Button onClick={() => reset(false)}>Done</Button>
            </DialogFooter>
          </div>
        ) : (
          <form onSubmit={onSubmit} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Invite someone</DialogTitle>
              <DialogDescription>
                They choose their own password. You can only hand out roles that carry no more
                access than you have.
              </DialogDescription>
            </DialogHeader>
            <Field label="Email" htmlFor="invite-to">
              <Input id="invite-to" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus required />
            </Field>
            <Field label="Role" htmlFor="invite-role">
              <Select value={roleId} items={items} onValueChange={(v) => setRoleId(v ?? '')}>
                <SelectTrigger id="invite-role" className="w-full">
                  <SelectValue placeholder="Choose a role" />
                </SelectTrigger>
                <SelectContent>
                  {items.map((i) => (
                    <SelectItem key={i.value} value={i.value}>
                      {i.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <DialogFooter>
              <Button type="submit" disabled={invite.isPending || !email.trim() || !roleId}>
                {invite.isPending ? <Loader2 className="animate-spin" /> : <Mail />} Create invitation
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

function MemberRow({ member, roles, isSelf }: { member: MemberOut; roles: AssignableRole[]; isSelf: boolean }) {
  const { client } = useAuth()
  const queryClient = useQueryClient()
  const [confirmRemove, setConfirmRemove] = useState(false)

  const change = useMutation({
    mutationFn: (roleId: string) => client.changeRole(member.user_id, roleId),
    onSuccess: (m) => {
      void queryClient.invalidateQueries({ queryKey: ['members'] })
      toast.success(`${m.display_name || m.email} is now ${m.role_name}`)
    },
    onError: (e) => toast.error(describeError(e)),
  })
  const remove = useMutation({
    mutationFn: () => client.removeMember(member.user_id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['members'] })
      toast.success(`Removed ${member.email}`)
    },
    onError: (e) => toast.error(describeError(e)),
  })

  const items = roles.map((r) => ({ value: r.id, label: r.name }))
  // A role you cannot grant is also one you cannot take away from someone, so show it read-only.
  const editable = !isSelf && roles.some((r) => r.id === member.role_id)

  return (
    <TableRow>
      <TableCell>
        <div className="font-medium">
          {member.display_name || member.email} {isSelf && <Badge variant="secondary">You</Badge>}
        </div>
        <div className="text-muted-foreground text-xs">{member.email}</div>
      </TableCell>
      <TableCell>
        {editable ? (
          <Select value={member.role_id} items={items} disabled={change.isPending} onValueChange={(v) => v && v !== member.role_id && change.mutate(v)}>
            <SelectTrigger className="w-40" aria-label={`Role for ${member.email}`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {items.map((i) => (
                <SelectItem key={i.value} value={i.value}>
                  {i.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <Badge variant="outline">{member.role_name}</Badge>
        )}
      </TableCell>
      <TableCell className="text-muted-foreground hidden md:table-cell">
        {member.last_login_at ? dateTimeFormat.format(new Date(member.last_login_at)) : 'Never'}
      </TableCell>
      <TableCell className="text-muted-foreground hidden lg:table-cell">
        {dateFormat.format(new Date(member.joined_at))}
      </TableCell>
      <TableCell className="text-right">
        {!isSelf && (
          <>
            <Button variant="ghost" size="icon" aria-label={`Remove ${member.email}`} onClick={() => setConfirmRemove(true)}>
              <Trash2 />
            </Button>
            <AlertDialog open={confirmRemove} onOpenChange={setConfirmRemove}>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Remove {member.email}?</AlertDialogTitle>
                  <AlertDialogDescription>
                    They lose access immediately and any signed-in sessions end. Their account is
                    kept, so they can be invited again.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction onClick={() => remove.mutate()}>Remove</AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </>
        )}
      </TableCell>
    </TableRow>
  )
}

export function TeamPage() {
  const { client, me, can } = useAuth()
  const queryClient = useQueryClient()
  const allowed = can('members:manage')

  const members = useQuery({ queryKey: ['members'], queryFn: () => client.members(), enabled: allowed })
  const roles = useQuery({ queryKey: ['assignable-roles'], queryFn: () => client.assignableRoles(), enabled: allowed })
  const invites = useQuery({ queryKey: ['invites'], queryFn: () => client.invites(), enabled: allowed })
  const revoke = useMutation({
    mutationFn: (id: string) => client.revokeInvite(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['invites'] })
      toast.success('Invitation withdrawn')
    },
    onError: (e) => toast.error(describeError(e)),
  })

  if (!allowed) {
    return (
      <Alert className="mx-auto max-w-2xl">
        <AlertTitle>No access</AlertTitle>
        <AlertDescription>You need the “manage members” permission to see the team.</AlertDescription>
      </Alert>
    )
  }

  return (
    <div className="mx-auto grid max-w-5xl gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Team</h1>
          <p className="text-muted-foreground text-sm">People who can sign in to this workspace, and what they can do.</p>
        </div>
        {roles.data && <InviteDialog roles={roles.data} />}
      </div>

      {members.isError && (
        <Alert variant="destructive">
          <AlertTitle>Could not load the team</AlertTitle>
          <AlertDescription>{describeError(members.error)}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Members</CardTitle>
          <CardDescription>Changing a role takes effect on their next request.</CardDescription>
        </CardHeader>
        <CardContent>
          {members.isPending ? (
            <div className="grid gap-3" aria-busy="true" aria-label="Loading members">
              {[0, 1].map((i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Person</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead className="hidden md:table-cell">Last sign-in</TableHead>
                  <TableHead className="hidden lg:table-cell">Joined</TableHead>
                  <TableHead className="w-16 text-right">
                    <span className="sr-only">Actions</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {members.data?.map((m) => (
                  <MemberRow key={m.user_id} member={m} roles={roles.data ?? []} isSelf={m.user_id === me?.user_id} />
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Pending invitations</CardTitle>
          <CardDescription>Links that have not been used yet.</CardDescription>
        </CardHeader>
        <CardContent>
          {invites.data && invites.data.length === 0 && (
            <p className="text-muted-foreground text-sm">No pending invitations.</p>
          )}
          {invites.data && invites.data.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Email</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead className="hidden sm:table-cell">Expires</TableHead>
                  <TableHead className="w-24 text-right">
                    <span className="sr-only">Actions</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {invites.data.map((i) => (
                  <TableRow key={i.id}>
                    <TableCell className="font-medium">{i.email}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{i.role_name}</Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground hidden sm:table-cell">{dateFormat.format(new Date(i.expires_at))}</TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="sm" onClick={() => revoke.mutate(i.id)} disabled={revoke.isPending} aria-label={`Withdraw invitation for ${i.email}`}>
                        Withdraw
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
