export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  if (seconds < 60) return `${seconds}s`
  const m = Math.floor(seconds / 60)
  return `${m}m ${String(seconds % 60).padStart(2, '0')}s`
}

export const STATUS_LABEL: Record<string, string> = {
  in_progress: 'In progress',
  completed: 'Completed',
  failed: 'Failed',
}

export const SOURCE_LABEL: Record<string, string> = {
  test: 'Test',
  inbound: 'Inbound',
  outbound: 'Outbound',
}
