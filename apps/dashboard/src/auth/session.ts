/** Where the API URL and key live. sessionStorage: gone when the tab closes, never in localStorage. */
const KEY = 'voizy.session'

export interface StoredSession {
  baseUrl: string
  key: string
}

export function loadSession(): StoredSession | null {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (!raw) return null
    const v = JSON.parse(raw) as Partial<StoredSession>
    return typeof v.baseUrl === 'string' && typeof v.key === 'string'
      ? { baseUrl: v.baseUrl, key: v.key }
      : null
  } catch {
    return null
  }
}

export function saveSession(s: StoredSession): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(s))
  } catch {
    /* storage unavailable: the session just won't survive a refresh */
  }
}

export function clearSession(): void {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    /* ignore */
  }
}

export function normalizeBaseUrl(input: string): string | null {
  try {
    const u = new URL(input.trim())
    if (u.protocol !== 'https:' && u.protocol !== 'http:') return null
    // Plain http is only acceptable for local development.
    if (u.protocol === 'http:' && !['localhost', '127.0.0.1'].includes(u.hostname)) return null
    return `${u.origin}`
  } catch {
    return null
  }
}
