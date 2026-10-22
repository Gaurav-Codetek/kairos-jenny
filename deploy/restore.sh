#!/usr/bin/env bash
# Load kairos-public.dump (from deploy/make_public_db.sh) into the deployed database.
#
#   bash deploy/restore.sh "postgresql://user:pass@host.render.com/kairos"     (Render's *External* Database URL)
#
# Runs pg_restore from the same Postgres image the app uses, so nothing needs installing. Restore before the API's first
# start, or into an empty database: the dump carries its own schema and migration version.
set -euo pipefail
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: leave container paths like /tmp alone
cd "$(dirname "$0")/.."
URL="${1:?usage: bash deploy/restore.sh <external database url>}"
[ -f kairos-public.dump ] || { echo "kairos-public.dump not found: run deploy/make_public_db.sh first"; exit 1; }

docker run --rm -v "$PWD:/d" pgvector/pgvector:pg16 sh -c \
  "psql '$URL' -v ON_ERROR_STOP=1 -c 'create extension if not exists vector' \
   && pg_restore --no-owner --no-privileges --clean --if-exists -d '$URL' /d/kairos-public.dump"
echo "restored"
