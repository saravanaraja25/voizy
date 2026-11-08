#!/bin/sh
# Creates the application's login role. It can never bypass RLS; the migration runner grants it
# membership of voizy_app once that role exists.
set -e
psql -v ON_ERROR_STOP=1 -v pw="$VOIZY_APP_DB_PASSWORD" \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE voizy_api LOGIN PASSWORD :'pw' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
SQL
