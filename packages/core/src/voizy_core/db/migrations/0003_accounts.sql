-- Human accounts: passwords, sessions, invites, first-run setup.
-- Same rule as everywhere else: forced RLS, narrow policies, column-level grants.

ALTER TABLE users
  ADD COLUMN password_hash text,
  ADD COLUMN is_active boolean NOT NULL DEFAULT true,
  ADD COLUMN last_login_at timestamptz;

-- First-run setup is claimed exactly once, atomically.
CREATE TABLE instance_settings (
  id boolean PRIMARY KEY DEFAULT true CHECK (id),  -- single row
  setup_completed_at timestamptz
);
INSERT INTO instance_settings DEFAULT VALUES;

CREATE FUNCTION forbid_unsetting_setup() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.setup_completed_at IS NOT NULL
     AND NEW.setup_completed_at IS DISTINCT FROM OLD.setup_completed_at THEN
    RAISE EXCEPTION 'setup can only be completed once';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER instance_settings_once BEFORE UPDATE ON instance_settings
  FOR EACH ROW EXECUTE FUNCTION forbid_unsetting_setup();

-- ---- users -------------------------------------------------------------------------------
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;

-- A workspace sees only its own members.
CREATE POLICY users_in_workspace ON users FOR SELECT
  USING (id IN (SELECT user_id FROM memberships WHERE workspace_id = app_workspace_id()));
-- Login: exactly the account whose email the caller presents.
CREATE POLICY users_login_lookup ON users FOR SELECT
  USING (lower(email) = nullif(current_setting('app.login_email', true), ''));
-- A signed-in user sees and updates themself.
CREATE POLICY users_self_select ON users FOR SELECT
  USING (id = nullif(current_setting('app.user_id', true), '')::uuid);
CREATE POLICY users_self_update ON users FOR UPDATE
  USING (id = nullif(current_setting('app.user_id', true), '')::uuid)
  WITH CHECK (id = nullif(current_setting('app.user_id', true), '')::uuid);
-- Creation: only the one email the transaction declared it is creating.
CREATE POLICY users_create ON users FOR INSERT
  WITH CHECK (lower(email) = nullif(current_setting('app.creating_email', true), ''));

-- A user can list their own memberships across workspaces (to pick one at login).
CREATE POLICY memberships_self ON memberships FOR SELECT
  USING (user_id = nullif(current_setting('app.user_id', true), '')::uuid);

GRANT INSERT (id, email, display_name, password_hash) ON users TO voizy_app;
GRANT UPDATE (password_hash, display_name, last_login_at, is_active) ON users TO voizy_app;
GRANT SELECT ON instance_settings TO voizy_app;
GRANT UPDATE (setup_completed_at) ON instance_settings TO voizy_app;

-- ---- sessions ----------------------------------------------------------------------------
CREATE TABLE sessions (
  token_hash bytea PRIMARY KEY,                 -- SHA-256 of the cookie value
  user_id uuid NOT NULL,
  workspace_id uuid NOT NULL,
  csrf_token text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  -- Removing someone from a workspace (or deleting them) ends their sessions there.
  FOREIGN KEY (workspace_id, user_id) REFERENCES memberships (workspace_id, user_id)
    ON DELETE CASCADE
);
CREATE INDEX sessions_user_idx ON sessions (user_id);

ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY session_by_token ON sessions
  USING (token_hash = decode(nullif(current_setting('app.session_hash', true), ''), 'hex'));
CREATE POLICY session_create ON sessions FOR INSERT
  WITH CHECK (user_id = nullif(current_setting('app.user_id', true), '')::uuid);
CREATE POLICY session_own_delete ON sessions FOR DELETE
  USING (user_id = nullif(current_setting('app.user_id', true), '')::uuid);
GRANT SELECT, INSERT, DELETE ON sessions TO voizy_app;
GRANT UPDATE (last_seen_at) ON sessions TO voizy_app;

-- ---- invites -----------------------------------------------------------------------------
CREATE TABLE invites (
  workspace_id uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  email text NOT NULL CHECK (length(email) BETWEEN 3 AND 254),
  role_id uuid NOT NULL,
  token_hash bytea NOT NULL UNIQUE,             -- the link's secret is never stored
  invited_by uuid REFERENCES users ON DELETE SET NULL,
  expires_at timestamptz NOT NULL,
  accepted_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, id),
  FOREIGN KEY (workspace_id, role_id) REFERENCES roles ON DELETE CASCADE
);
CREATE UNIQUE INDEX invites_one_pending_per_email ON invites (workspace_id, lower(email))
  WHERE accepted_at IS NULL AND revoked_at IS NULL;

ALTER TABLE invites ENABLE ROW LEVEL SECURITY;
ALTER TABLE invites FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON invites USING (workspace_id = app_workspace_id())
  WITH CHECK (workspace_id = app_workspace_id());
-- Accepting: the one invite whose secret the caller holds, read and mark-accepted only.
CREATE POLICY invite_by_token_select ON invites FOR SELECT
  USING (token_hash = decode(nullif(current_setting('app.invite_hash', true), ''), 'hex'));
CREATE POLICY invite_by_token_update ON invites FOR UPDATE
  USING (token_hash = decode(nullif(current_setting('app.invite_hash', true), ''), 'hex'))
  WITH CHECK (token_hash = decode(nullif(current_setting('app.invite_hash', true), ''), 'hex'));
GRANT SELECT, INSERT, UPDATE, DELETE ON invites TO voizy_app;
