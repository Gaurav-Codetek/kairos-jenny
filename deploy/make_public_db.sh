#!/usr/bin/env bash
# A copy of the local Kairos database that is safe to deploy publicly: the ICS Sales Warehouse connection and
# everything mirrored or learned from it removed (the database cascades from the connection), its agent activity and
# all evaluation runs dropped, and a final sweep that fails if any trace of it is left.
#
#   bash deploy/make_public_db.sh            (from the repo root, with `docker compose up` running)
#
# Writes kairos-public.dump (pg_dump custom format) for deploy/restore.sh. Your working database is not touched: the
# work happens in a scratch database, kairos_public, inside the same Postgres container.
set -euo pipefail
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: leave container paths like /tmp alone
cd "$(dirname "$0")/.."

HIDE_NAME="ICS Sales Warehouse"
PATTERN='(ICS Sales|ics_sales|ics-sales)'
psql() { docker compose exec -T db psql -U kairos -d kairos_public -v ON_ERROR_STOP=1 -q "$@"; }

echo "1/4 copying the database to kairos_public"
docker compose exec -T db sh -c "dropdb -U kairos --if-exists kairos_public && createdb -U kairos kairos_public \
  && pg_dump -U kairos -Fc kairos | pg_restore -U kairos -d kairos_public --no-owner"

echo "2/4 removing $HIDE_NAME and its traces"
psql <<SQL
delete from workspaces where name = '$HIDE_NAME';
delete from agent_activity
 where channel ~* 'ics' or arguments::text ~* '$PATTERN' or entity_ids::text ~* '$PATTERN' or error ~* '$PATTERN';
delete from eval_threads;
delete from eval_runs;
SQL

echo "3/4 sweeping every text column for anything left"
psql -t -A <<SQL
do \$\$
declare r record; n bigint; total bigint := 0;
begin
  for r in select table_name, column_name from information_schema.columns
           where table_schema = 'public' and data_type in ('text', 'character varying', 'json', 'jsonb')
  loop
    execute format('select count(*) from %I where %I::text ~* %L', r.table_name, r.column_name, '$PATTERN') into n;
    if n > 0 then raise notice '% . % : % rows', r.table_name, r.column_name, n; total := total + n; end if;
  end loop;
  if total > 0 then raise exception 'still % rows mentioning it: not safe to publish', total; end if;
end \$\$;
SQL

echo "4/4 writing kairos-public.dump"
docker compose exec -T db pg_dump -U kairos -Fc -f /tmp/kairos-public.dump kairos_public
docker compose cp db:/tmp/kairos-public.dump ./kairos-public.dump
ls -la kairos-public.dump
echo "done: restore it with  bash deploy/restore.sh \"<Render external database URL>\""
