import { Field } from '@/components/field'
import { Input } from '@/components/ui/input'

export const MIN_PASSWORD = 10

export function passwordProblem(password: string, confirm: string): string | null {
  if (password.length < MIN_PASSWORD) return `Use at least ${MIN_PASSWORD} characters.`
  if (password !== confirm) return 'The passwords do not match.'
  return null
}

/** New-password + confirmation, with the rule stated up front rather than discovered on error. */
export function PasswordFields({
  idPrefix,
  password,
  confirm,
  onPassword,
  onConfirm,
  label = 'Password',
}: {
  idPrefix: string
  password: string
  confirm: string
  onPassword: (v: string) => void
  onConfirm: (v: string) => void
  label?: string
}) {
  return (
    <>
      <Field
        label={label}
        htmlFor={`${idPrefix}-password`}
        hint={`At least ${MIN_PASSWORD} characters. A long passphrase works best.`}
      >
        <Input
          id={`${idPrefix}-password`}
          type="password"
          value={password}
          onChange={(e) => onPassword(e.target.value)}
          autoComplete="new-password"
          required
        />
      </Field>
      <Field label="Confirm password" htmlFor={`${idPrefix}-confirm`}>
        <Input
          id={`${idPrefix}-confirm`}
          type="password"
          value={confirm}
          onChange={(e) => onConfirm(e.target.value)}
          autoComplete="new-password"
          required
        />
      </Field>
    </>
  )
}
