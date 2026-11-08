-- Call history. Transcripts are personal data: what is stored is decided per agent (retention,
-- redaction, opt-out) before a row is written, and rows expire.

CREATE TABLE calls (
  workspace_id uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  agent_id uuid NOT NULL,
  agent_version int NOT NULL CHECK (agent_version > 0),
  source text NOT NULL CHECK (source IN ('test', 'inbound', 'outbound')),
  room text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress', 'completed', 'failed')),
  started_at timestamptz NOT NULL DEFAULT now(),
  ended_at timestamptz,
  duration_s int CHECK (duration_s >= 0),
  end_reason text NOT NULL DEFAULT '' CHECK (length(end_reason) <= 200),
  turn_count int NOT NULL DEFAULT 0,
  latency_p50_ms int,
  transcript_stored boolean NOT NULL DEFAULT true,  -- false: only metadata was kept
  expires_at timestamptz,                            -- NULL = keep until someone deletes it
  PRIMARY KEY (workspace_id, id),
  FOREIGN KEY (workspace_id, agent_id) REFERENCES agents
);
CREATE INDEX calls_recent ON calls (workspace_id, started_at DESC, id DESC);
CREATE INDEX calls_by_room ON calls (workspace_id, room) WHERE room <> '';
CREATE INDEX calls_expiry ON calls (workspace_id, expires_at) WHERE expires_at IS NOT NULL;

CREATE TABLE call_turns (
  workspace_id uuid NOT NULL,
  call_id uuid NOT NULL,
  seq int NOT NULL CHECK (seq >= 0),
  role text NOT NULL CHECK (role IN ('user', 'agent', 'tool')),
  text text NOT NULL DEFAULT '' CHECK (length(text) <= 8000),
  -- Tool turns record that a tool ran, never its arguments or result (those can hold PII).
  tool_name text CHECK (length(tool_name) <= 64),
  tool_ok boolean,
  tool_ms int,
  latency jsonb,                                    -- per-stage milliseconds for agent turns
  at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, call_id, seq),
  FOREIGN KEY (workspace_id, call_id) REFERENCES calls ON DELETE CASCADE
);

ALTER TABLE calls ENABLE ROW LEVEL SECURITY;
ALTER TABLE calls FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON calls USING (workspace_id = app_workspace_id())
  WITH CHECK (workspace_id = app_workspace_id());
ALTER TABLE call_turns ENABLE ROW LEVEL SECURITY;
ALTER TABLE call_turns FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON call_turns USING (workspace_id = app_workspace_id())
  WITH CHECK (workspace_id = app_workspace_id());

-- Turns are append-only. Calls are updated while in progress and deleted by retention or an operator
-- (deleting a call cascades to its turns).
GRANT SELECT, INSERT, UPDATE, DELETE ON calls TO voizy_app;
GRANT SELECT, INSERT ON call_turns TO voizy_app;
