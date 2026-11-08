# Security and design principles

Rules the code is held to. Each has a test or is marked *planned*.

**Tenancy**
- Every tenant table carries `workspace_id` and has Postgres RLS enabled *and forced*.
- The app connects as a non-owner role without `BYPASSRLS`; each transaction sets
  `app.workspace_id` with `set_config(..., true)`. Missing setting means zero rows.
- Cross-tenant references are prevented by composite foreign keys `(workspace_id, id)`.

**Access control**
- Permissions are code-defined; roles are data; handlers check permissions, never role names.
- No escalation (grant only what you hold), locked superadmin role, last-superadmin protection,
  API keys bounded by their creator. Role changes are audited.

**Accounts and sessions**
- Passwords: argon2id (64 MiB, t=3, 4 lanes), 10-128 characters, common-password and
  email-in-password checks. Unknown accounts are hash-checked against a dummy so timing does not
  reveal which emails exist; failures return one generic message.
- Login is throttled per account (5 / 15 min) and per address (30 / 15 min), in memory per
  process (put a shared limiter in front for multi-instance deployments).
- Sessions: 256-bit random token in an HttpOnly, SameSite=Lax cookie (Secure unless disabled for
  local http); only its SHA-256 is stored. Absolute 14-day and 3-day idle expiry. Removing a
  member deletes their sessions (foreign-key cascade); a password change ends all other sessions.
- CSRF: cookie-authenticated writes need the per-session `X-CSRF-Token` and an allowlisted
  `Origin`. API-key requests are exempt (browsers never attach them on their own). CORS allows
  credentials only for explicitly listed origins; a wildcard is ignored.
- First-run setup: needs a one-time token printed to the server log, and the claim is an atomic
  update that can never be undone, so a freshly exposed instance cannot be taken over.
- Invitations: the link secret is never stored (hash only), works once (row-locked), expires in
  7 days, and cannot grant a role above the inviter's own permissions.
- The `users` table has forced RLS with narrow policies (login-by-email, self, workspace
  members, create-declared-email) and column-level grants: the app role cannot set the
  platform-superadmin flag. Account functions refuse a non-idle connection, because a nested
  savepoint would leak the transaction-local security context.
- The browser keeps no credential: identity and the CSRF token live in memory only, the query
  cache is cleared on every session change, and nothing is written to local/session storage.

**Secrets**
- Provider keys and tool credentials are AES-256-GCM encrypted with workspace and name bound as
  associated data, versioned keys for rotation, write-only through the API. Configs reference
  secrets by name and never contain them. API keys are stored as SHA-256 of a 256-bit random token
  (shown once); passwords (when added) use argon2id.

**Outbound requests**
- HTTP tools and webhooks go through the SSRF guard: https only, port 443, every resolved IP must
  be global, connect to the validated IP, no redirects, short timeouts, response size caps
  *(runtime enforcement planned with the tool executor)*.
- Webhooks are signed with HMAC-SHA256 over timestamp plus body *(planned)*.

**Input and prompts**
- Strict pydantic models (`extra=forbid`). Prompt variables render in one pass, never re-scanned.
- Caller speech and tool output are untrusted: tools get least privilege, side-effecting built-ins
  are parameter-validated, and the model never sees secrets.

**Telephony and compliance**
- Twilio webhook signatures are verified *(planned)*. Outbound calls pass a consent/DND/quiet-hours
  policy gate before dialing. Recording requires a configured disclosure.
- Transcripts and recordings follow per-workspace retention; PII redaction on by default.

**Operations**
- Secrets only from environment, `.env` is git-ignored, no secrets in logs (`repr` redacts).
- Audit log is append-only (no UPDATE/DELETE grants for the app role).
- Dependencies pinned by `uv.lock`; CI runs ruff (incl. bandit rules), mypy strict, tests.
