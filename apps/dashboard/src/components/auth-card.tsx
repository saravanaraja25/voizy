import { AudioLines } from 'lucide-react'
import type { ReactNode } from 'react'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'

/** The shared frame for every signed-out screen. */
export function AuthCard({
  title,
  description,
  children,
  footer,
  onSubmit,
}: {
  title: string
  description?: ReactNode
  children: ReactNode
  footer?: ReactNode
  onSubmit?: (e: React.FormEvent) => void
}) {
  const body = (
    <>
      <CardHeader>
        <div className="bg-primary text-primary-foreground mb-2 flex size-10 items-center justify-center rounded-lg">
          <AudioLines className="size-5" />
        </div>
        <CardTitle className="text-xl" role="heading" aria-level={1}>
          {title}
        </CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent className="mt-4 grid gap-4">{children}</CardContent>
      {footer && <CardFooter className="mt-6 flex-col items-stretch gap-3">{footer}</CardFooter>}
    </>
  )
  return (
    <div className="bg-muted/40 flex min-h-svh items-center justify-center p-4">
      <Card className="w-full max-w-md">
        {onSubmit ? (
          <form onSubmit={onSubmit} noValidate>
            {body}
          </form>
        ) : (
          body
        )}
      </Card>
    </div>
  )
}
