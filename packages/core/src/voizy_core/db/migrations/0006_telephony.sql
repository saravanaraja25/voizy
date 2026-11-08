-- Phone numbers connected through a Twilio Elastic SIP trunk into LiveKit SIP.
-- Provider-side ids are kept so a number can be fully disconnected later. No secrets live here:
-- the per-number SIP password exists only inside Twilio and LiveKit.

CREATE TABLE telephony_trunks (
  workspace_id uuid PRIMARY KEY REFERENCES workspaces ON DELETE CASCADE,
  twilio_trunk_sid text NOT NULL,
  termination_domain text NOT NULL,
  twilio_credential_list_sid text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE phone_numbers (
  workspace_id uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  e164 text NOT NULL CHECK (e164 ~ '^\+[1-9][0-9]{6,14}$'),
  label text NOT NULL DEFAULT '' CHECK (length(label) <= 80),
  agent_id uuid,                                   -- answers inbound calls; NULL = rejects them
  twilio_number_sid text NOT NULL,
  twilio_credential_sid text NOT NULL,
  lk_inbound_trunk_id text NOT NULL,
  lk_dispatch_rule_id text NOT NULL,
  lk_outbound_trunk_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, id),
  FOREIGN KEY (workspace_id, agent_id) REFERENCES agents
);
-- One workspace owns a number at a time, enforced across all workspaces.
CREATE UNIQUE INDEX phone_numbers_e164 ON phone_numbers (e164);

ALTER TABLE telephony_trunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE telephony_trunks FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON telephony_trunks USING (workspace_id = app_workspace_id())
  WITH CHECK (workspace_id = app_workspace_id());
ALTER TABLE phone_numbers ENABLE ROW LEVEL SECURITY;
ALTER TABLE phone_numbers FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON phone_numbers USING (workspace_id = app_workspace_id())
  WITH CHECK (workspace_id = app_workspace_id());

GRANT SELECT, INSERT, DELETE ON telephony_trunks TO voizy_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON phone_numbers TO voizy_app;
