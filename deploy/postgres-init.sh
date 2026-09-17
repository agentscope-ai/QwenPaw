#!/bin/sh
set -eu

schema="${WELDON_DB_SCHEMA:-weldonagent}"
case "$schema" in
  ''|[0-9]*|*[!A-Za-z0-9_]*)
    echo "WELDON_DB_SCHEMA must be a valid PostgreSQL identifier" >&2
    exit 1
    ;;
esac

psql \
  --set=ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=schema="$schema" \
  --set=owner="$POSTGRES_USER" <<'SQL'
SELECT format(
  'CREATE SCHEMA IF NOT EXISTS %I AUTHORIZATION %I',
  :'schema',
  :'owner'
) \gexec
SQL
