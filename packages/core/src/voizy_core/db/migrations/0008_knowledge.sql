-- Knowledge base: documents are split into chunks and searched with Postgres full-text search.
-- (No embeddings service or extension is needed; lookups are single-digit milliseconds.)

CREATE TABLE kb_documents (
  workspace_id uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  collection text NOT NULL DEFAULT 'default' CHECK (collection ~ '^[a-z0-9][a-z0-9_-]{0,39}$'),
  title text NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
  source_name text NOT NULL DEFAULT '' CHECK (length(source_name) <= 200),
  bytes int NOT NULL CHECK (bytes >= 0),
  chunk_count int NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, id)
);
CREATE INDEX kb_documents_by_collection ON kb_documents (workspace_id, collection, created_at DESC);

CREATE TABLE kb_chunks (
  workspace_id uuid NOT NULL,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL,
  collection text NOT NULL,
  seq int NOT NULL CHECK (seq >= 0),
  heading text NOT NULL DEFAULT '' CHECK (length(heading) <= 200),
  content text NOT NULL CHECK (length(content) BETWEEN 1 AND 4000),
  tsv tsvector GENERATED ALWAYS AS (
    to_tsvector('english', coalesce(heading, '') || ' ' || content)
  ) STORED,
  PRIMARY KEY (workspace_id, id),
  FOREIGN KEY (workspace_id, document_id) REFERENCES kb_documents ON DELETE CASCADE
);
CREATE INDEX kb_chunks_tsv ON kb_chunks USING gin (tsv);
CREATE INDEX kb_chunks_by_document ON kb_chunks (workspace_id, document_id, seq);

ALTER TABLE kb_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE kb_documents FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON kb_documents USING (workspace_id = app_workspace_id())
  WITH CHECK (workspace_id = app_workspace_id());
ALTER TABLE kb_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE kb_chunks FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON kb_chunks USING (workspace_id = app_workspace_id())
  WITH CHECK (workspace_id = app_workspace_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON kb_documents TO voizy_app;
GRANT SELECT, INSERT, DELETE ON kb_chunks TO voizy_app;
