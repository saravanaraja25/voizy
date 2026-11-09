export const CAMPAIGN_STATUS: Record<string, string> = {
  draft: 'Draft',
  running: 'Running',
  paused: 'Paused',
  completed: 'Completed',
  cancelled: 'Cancelled',
}

export const CONTACT_STATUS: Record<string, string> = {
  pending: 'Waiting',
  calling: 'Calling',
  completed: 'Reached',
  no_answer: 'No answer',
  voicemail: 'Voicemail',
  failed: 'Failed',
  opted_out: 'Asked not to be called',
  dnc: 'Do not call',
}

export const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

/** Contacts that need no more work, used for the progress bar. */
export const FINISHED = ['completed', 'no_answer', 'voicemail', 'failed', 'opted_out', 'dnc']

export function progress(counts: Record<string, number>): { total: number; done: number } {
  const total = Object.values(counts).reduce((a, b) => a + b, 0)
  const done = FINISHED.reduce((a, k) => a + (counts[k] ?? 0), 0)
  return { total, done }
}

export function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}
