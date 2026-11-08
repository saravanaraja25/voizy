import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'

export function NotFoundPage() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-3 py-24 text-center">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="text-muted-foreground text-sm">That page does not exist or has moved.</p>
      <Button render={<Link to="/" />} nativeButton={false}>Back to agents</Button>
    </div>
  )
}
