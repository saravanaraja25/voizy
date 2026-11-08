-- Secrets get a kind and, for tool credentials, the hosts they may be sent to.
-- A tool credential that could go anywhere could be exfiltrated by pointing a tool elsewhere.
ALTER TABLE secrets
  ADD COLUMN kind text NOT NULL DEFAULT 'tool' CHECK (kind IN ('integration', 'tool')),
  ADD COLUMN allowed_hosts text[] NOT NULL DEFAULT '{}',
  ADD COLUMN description text NOT NULL DEFAULT '' CHECK (length(description) <= 200),
  ADD COLUMN hint text NOT NULL DEFAULT '',          -- e.g. '••••abcd'; the value is never recoverable here
  ADD COLUMN created_at timestamptz NOT NULL DEFAULT now(),
  ADD CONSTRAINT tool_secret_needs_hosts CHECK (kind <> 'tool' OR cardinality(allowed_hosts) > 0);

-- The deployment's own workspace, recorded once. Deployment-wide resources (the voice worker's
-- LiveKit connection) belong to it. It sits outside tenant RLS so the worker can find it at start-up.
ALTER TABLE instance_settings ADD COLUMN primary_workspace_id uuid REFERENCES workspaces;
GRANT UPDATE (primary_workspace_id) ON instance_settings TO voizy_app;

CREATE FUNCTION forbid_changing_primary_workspace() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.primary_workspace_id IS NOT NULL
     AND NEW.primary_workspace_id IS DISTINCT FROM OLD.primary_workspace_id THEN
    RAISE EXCEPTION 'the primary workspace can only be set once';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER instance_primary_workspace_once BEFORE UPDATE ON instance_settings
  FOR EACH ROW EXECUTE FUNCTION forbid_changing_primary_workspace();
