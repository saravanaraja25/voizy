-- Voizy initial schema. Every tenant table: workspace_id + FORCED row level security.
-- The application connects as voizy_app (no BYPASSRLS, not the table owner).

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'voizy_app') THEN
    CREATE ROLE voizy_app NOLOGIN NOBYPASSRLS;
  END IF;
END $$;

-- Current workspace for this transaction; NULL (=> no rows) when unset.
CREATE FUNCTION app_workspace_id() RETURNS uuid
  LANGUAGE sql STABLE AS
  $$ SELECT nullif(current_setting('app.workspace_id', true), '')::uuid $$;

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text NOT NULL,
  display_name text NOT NULL DEFAULT '',
  is_platform_superadmin boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX users_email_lower_key ON users (lower(email));

CREATE TABLE workspaces (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE roles (
  workspace_id uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  name text NOT NULL CHECK (length(name) BETWEEN 1 AND 60),
  is_system boolean NOT NULL DEFAULT false,
  is_locked boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, id),
  UNIQUE (workspace_id, name)
);

CREATE TABLE role_permissions (
  workspace_id uuid NOT NULL,
  role_id uuid NOT NULL,
  permission text NOT NULL,
  PRIMARY KEY (workspace_id, role_id, permission),
  FOREIGN KEY (workspace_id, role_id) REFERENCES roles ON DELETE CASCADE
);

CREATE TABLE memberships (
  workspace_id uuid NOT NULL,
  user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  role_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, user_id),
  FOREIGN KEY (workspace_id, role_id) REFERENCES roles
);

CREATE TABLE api_keys (
  workspace_id uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  name text NOT NULL,
  prefix text NOT NULL,
  key_hash bytea NOT NULL UNIQUE,  -- SHA-256 of a 256-bit random token; token shown once
  permissions text[] NOT NULL,
  created_by uuid REFERENCES users ON DELETE SET NULL,
  expires_at timestamptz,
  revoked_at timestamptz,
  last_used_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, id)
);

CREATE TABLE secrets (
  workspace_id uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  name text NOT NULL CHECK (name ~ '^[a-z][a-z0-9_]{0,63}$'),
  ciphertext text NOT NULL,  -- SecretBox token; never returned by the API
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, name)
);

CREATE TABLE agents (
  workspace_id uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  name text NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
  published_version_id uuid,
  archived_at timestamptz,
  created_by uuid REFERENCES users ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, id)
);

CREATE TABLE agent_versions (
  workspace_id uuid NOT NULL,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  agent_id uuid NOT NULL,
  version int NOT NULL CHECK (version > 0),
  config jsonb NOT NULL,        -- validated AgentConfig; immutable once published
  is_published boolean NOT NULL DEFAULT false,
  published_at timestamptz,
  created_by uuid REFERENCES users ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, id),
  UNIQUE (workspace_id, agent_id, version),
  FOREIGN KEY (workspace_id, agent_id) REFERENCES agents ON DELETE CASCADE
);

ALTER TABLE agents ADD FOREIGN KEY (workspace_id, published_version_id)
  REFERENCES agent_versions (workspace_id, id);

-- Published versions are immutable.
CREATE FUNCTION forbid_published_version_change() RETURNS trigger
  LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.is_published AND (NEW.config IS DISTINCT FROM OLD.config
      OR NEW.version <> OLD.version OR NEW.is_published = false) THEN
    RAISE EXCEPTION 'published agent versions are immutable';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER agent_versions_immutable BEFORE UPDATE ON agent_versions
  FOR EACH ROW EXECUTE FUNCTION forbid_published_version_change();

CREATE TABLE audit_log (
  workspace_id uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  id bigint GENERATED ALWAYS AS IDENTITY,
  actor_user_id uuid,
  actor_api_key_id uuid,
  action text NOT NULL,
  target_type text NOT NULL,
  target_id text,
  detail jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, id)
);

-- Row level security -------------------------------------------------------------------------
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['roles','role_permissions','memberships','api_keys','secrets',
                           'agents','agent_versions','audit_log']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I USING (workspace_id = app_workspace_id())
         WITH CHECK (workspace_id = app_workspace_id())', t);
  END LOOP;
END $$;

-- A workspace row is visible only when it is the current workspace.
ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspaces FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON workspaces USING (id = app_workspace_id());

-- Grants: least privilege. Audit log is append-only; users table is read-only for the app role
-- (account management goes through a separate, narrower path added with auth).
GRANT SELECT, INSERT, UPDATE, DELETE ON
  workspaces, roles, role_permissions, memberships, api_keys, secrets, agents, agent_versions
  TO voizy_app;
GRANT SELECT, INSERT ON audit_log TO voizy_app;
GRANT SELECT ON users TO voizy_app;
