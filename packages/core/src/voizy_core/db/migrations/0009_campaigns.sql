-- Outbound campaigns: a contact list worked through an agent inside a calling window, with retries
-- and a workspace-wide do-not-call list that is checked at the moment of dialing.

CREATE TABLE dnc_numbers (
  workspace_id uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  e164 text NOT NULL CHECK (e164 ~ '^\+[1-9][0-9]{6,14}$'),
  source text NOT NULL CHECK (source IN ('manual', 'opt_out', 'import')),
  note text NOT NULL DEFAULT '' CHECK (length(note) <= 200),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, e164)
);

CREATE TABLE campaigns (
  workspace_id uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  name text NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
  agent_id uuid NOT NULL,
  from_number_id uuid NOT NULL,
  status text NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'running', 'paused', 'completed', 'cancelled')),
  timezone text NOT NULL DEFAULT 'UTC',             -- default for contacts without their own
  days_mask int NOT NULL DEFAULT 31 CHECK (days_mask BETWEEN 1 AND 127),  -- bit0 = Monday
  window_start time NOT NULL DEFAULT '09:00',
  window_end time NOT NULL DEFAULT '17:00',
  max_concurrent int NOT NULL DEFAULT 1 CHECK (max_concurrent BETWEEN 1 AND 10),
  max_attempts int NOT NULL DEFAULT 2 CHECK (max_attempts BETWEEN 1 AND 5),
  retry_delay_min int NOT NULL DEFAULT 60 CHECK (retry_delay_min BETWEEN 5 AND 10080),
  consent_confirmed_at timestamptz,
  consent_confirmed_by uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  completed_at timestamptz,
  PRIMARY KEY (workspace_id, id),
  CHECK (window_start < window_end),
  FOREIGN KEY (workspace_id, agent_id) REFERENCES agents,
  FOREIGN KEY (workspace_id, from_number_id) REFERENCES phone_numbers
);

CREATE TABLE campaign_contacts (
  workspace_id uuid NOT NULL,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  campaign_id uuid NOT NULL,
  e164 text NOT NULL CHECK (e164 ~ '^\+[1-9][0-9]{6,14}$'),
  name text NOT NULL DEFAULT '' CHECK (length(name) <= 100),
  timezone text,                                    -- NULL = the campaign's
  variables jsonb NOT NULL DEFAULT '{}',            -- prompt variables for this person
  status text NOT NULL DEFAULT 'pending' CHECK (status IN
    ('pending', 'calling', 'completed', 'no_answer', 'voicemail', 'failed', 'opted_out', 'dnc')),
  attempts int NOT NULL DEFAULT 0,
  next_attempt_at timestamptz,
  claimed_at timestamptz,
  last_outcome text,
  last_error text NOT NULL DEFAULT '' CHECK (length(last_error) <= 200),
  -- clock_timestamp, not now(): rows imported in one transaction must keep their file order.
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (workspace_id, id),
  UNIQUE (workspace_id, campaign_id, e164),
  FOREIGN KEY (workspace_id, campaign_id) REFERENCES campaigns ON DELETE CASCADE
);
CREATE INDEX campaign_contacts_due
  ON campaign_contacts (workspace_id, campaign_id, status, next_attempt_at);

ALTER TABLE calls ADD COLUMN campaign_id uuid;
ALTER TABLE calls ADD COLUMN contact_id uuid;
CREATE INDEX calls_by_contact ON calls (workspace_id, contact_id) WHERE contact_id IS NOT NULL;

ALTER TABLE dnc_numbers ENABLE ROW LEVEL SECURITY;
ALTER TABLE dnc_numbers FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON dnc_numbers USING (workspace_id = app_workspace_id())
  WITH CHECK (workspace_id = app_workspace_id());
ALTER TABLE campaigns ENABLE ROW LEVEL SECURITY;
ALTER TABLE campaigns FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON campaigns USING (workspace_id = app_workspace_id())
  WITH CHECK (workspace_id = app_workspace_id());
ALTER TABLE campaign_contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE campaign_contacts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON campaign_contacts USING (workspace_id = app_workspace_id())
  WITH CHECK (workspace_id = app_workspace_id());

GRANT SELECT, INSERT, DELETE ON dnc_numbers TO voizy_app;
GRANT SELECT, INSERT, UPDATE ON campaigns TO voizy_app;
GRANT SELECT, INSERT, UPDATE ON campaign_contacts TO voizy_app;
