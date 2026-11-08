import type { ReactNode } from 'react'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

interface FieldProps {
  label: string
  htmlFor: string
  hint?: ReactNode
  error?: string
  className?: string
  children: ReactNode
}

/** Label + control + hint + inline validation message, wired for screen readers. */
export function Field({ label, htmlFor, hint, error, className, children }: FieldProps) {
  return (
    <div className={cn('grid content-start gap-2', className)}>
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {error ? (
        <p id={`${htmlFor}-error`} role="alert" className="text-destructive text-sm">
          {error}
        </p>
      ) : hint ? (
        <p id={`${htmlFor}-hint`} className="text-muted-foreground text-xs">
          {hint}
        </p>
      ) : null}
    </div>
  )
}

export interface TabProps<T> {
  config: T
  onChange: (next: T) => void
  errors: Record<string, string>
  disabled?: boolean
}
