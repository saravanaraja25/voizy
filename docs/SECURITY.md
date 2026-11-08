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
