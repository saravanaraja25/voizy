-- Secrets get a kind and, for tool credentials, the hosts they may be sent to.
-- A tool credential that could go anywhere could be exfiltrated by pointing a tool elsewhere.
ALTER TABLE secrets
  ADD COLUMN kind text NOT NULL DEFAULT 'tool' CHECK (kind IN ('integration', 'tool')),
  ADD COLUMN allowed_hosts text[] NOT NULL DEFAULT '{}',
  ADD COLUMN description text NOT NULL DEFAULT '' CHECK (length(description) <= 200),
  ADD COLUMN hint text NOT NULL DEFAULT '',          -- e.g. '••••abcd'; the value is never recoverable here
  ADD COLUMN created_at timestamptz NOT NULL DEFAULT now(),
  ADD CONSTRAINT tool_secret_needs_hosts CHECK (kind <> 'tool' OR cardinality(allowed_hosts) > 0);
