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

**Integration keys and tool credentials**
- Stored per workspace in the encrypted secret store (AES-256-GCM, workspace and name bound as
  associated data, versioned keyring from `VOIZY_SECRET_KEYS`). Nothing returns a value: the API
  shows a masked hint, and only non-sensitive fields (a URL, an account id) are shown back.
- Two kinds that cannot read each other: integration keys (reserved names) and tool credentials.
  A tool can only resolve `kind = tool`, so it can never reach an integration key.
- A tool credential is pinned to the hosts it may be sent to (exact or `*.example.com`, never an IP
  literal). The executor resolves it only after the destination passes the SSRF checks, refuses if
  the host is not on the list (without revealing the list), never follows redirects, and error
  messages never carry the value. A tool config names a credential; it never contains one.
- 'Test connection' makes one read-only call per provider, never follows redirects, and applies the
  tool-call destination checks to the operator-supplied LiveKit URL.
- Audit entries record that a secret changed and which hosts, never its value.

**Call history and privacy**
- A transcript is personal data, so what is stored is decided before a row is written, per agent
  (`policy`): keep transcripts or not (`save_transcripts`), best-effort redaction of emails, card,
  phone and ID-like numbers including spoken digits (`redact_pii`), and an expiry on every call
  (`retention_days`; metadata-only calls keep 30 days). Redaction is a safety net, not a guarantee.
- Tool turns record only the tool name, success and duration, never arguments or results.
- Transcripts need their own permission (`calls:view_transcript`); deleting a call needs
  `calls:delete` and is audited. Expired calls are purged hourly and abandoned in-progress calls
  are closed.
- Recording is isolated from the call: the audio path only enqueues, one background task writes,
  and any failure is logged without content and dropped.
- Worker logs carry no transcript unless `VOIZY_LOG_TRANSCRIPTS=1` (off by default).

**Telephony**
- The LiveKit inbound trunk accepts SIP only from Twilio's published signaling ranges and only for
  the connected number. The Twilio auth token is encrypted, write-only and used only server-side.
- Phone numbers are unique across workspaces; call dispatch metadata is set by the server, never
  by a caller or browser. Outbound calls need `calls:place_outbound`, explicit consent, a published
  agent, and are capped per workspace; audit entries keep only the last four digits dialed.
- The other party's number is stored with the call and masked in the API and dashboard unless the
  reader holds `calls:view_pii`; it expires with the call. The dialed number reaches the worker in
  server-signed dispatch metadata and is validated as E.164.
- Provider-side ids stay server-side; the per-number SIP password exists only inside Twilio and
  LiveKit. See [TELEPHONY.md](TELEPHONY.md).

**Knowledge base**
- Documents are tenant-isolated (forced RLS), writes need `kb:manage`, and only plain text is
  accepted (no HTML, no binary: a NUL byte is refused). Retrieved passages are labelled as
  information, not instructions, and the call rules come last; a document that tries to give the
  agent orders was tested and not obeyed. Logs record counts, never text.

**Campaigns and do-not-call**
- Creating a campaign records who confirmed consent and when. Calls go out only inside the chosen
  window in the contact's timezone. The do-not-call list is checked at import *and* at dial time.
  Opt-outs spoken on a call are honored immediately and workspace-wide.
- Contact numbers are masked unless the reader holds `calls:view_pii`; audit entries keep at most
  the last four digits. CSV columns can only fill prompt variables the agent declares and cannot
  override system variables. Cross-workspace access is blocked by row-level security.

**Direct provider keys**
- A component set to "my key" uses the stored provider key, never silently falls back to LiveKit,
  and is rejected at save time if the provider is unsupported or the key is missing.

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
