/**
 * The current session's CSRF token, held in memory only. It is not a credential on its own (the
 * HttpOnly session cookie is), and it is deliberately never written to browser storage.
 */
let token: string | null = null

export const getCsrf = (): string | null => token
export const setCsrf = (value: string | null): void => {
  token = value
}
