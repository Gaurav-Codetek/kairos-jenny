"""Copy one connection's enrichment profiles (their YAML) into a database's entity_profiles.content.

Profiles used to live only as files under data/profiles, which never reach Render (data/ is not in the image, and its
disk is reset on every deploy). Since migration b5e1c7a9d3f2 each profile's YAML is kept in the database too. This
fills that copy for profiles written before then:

    # fill your local database from the files (run once)
    docker compose exec api python deploy/push_profiles.py --workspace "Zomato Snowflake"

    # then copy them to Render (its External Database URL; the API there must already run the new code)
    docker compose exec api python deploy/push_profiles.py --workspace "Zomato Snowflake" --to "postgresql://..."

Only the named connection's profiles are read, and only rows the target already has are updated (the target got them
from restore.sh): nothing of any other connection is ever sent.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import ssl
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kairos_kb.config import get_settings  # noqa: E402


def plain(url: str) -> str:
    return re.sub(r"^postgres(ql)?(\+asyncpg)?://", "postgresql://", url)


async def connect(url: str, remote: bool) -> asyncpg.Connection:
    if not remote:
        return await asyncpg.connect(plain(url))
    ctx = ssl.create_default_context()
    return await asyncpg.connect(plain(url), ssl=ctx)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True, help="the connection's name, e.g. 'Zomato Snowflake'")
    ap.add_argument("--to", help="the target database URL; omitted: fill the local database")
    ap.add_argument("--force", action="store_true", help="overwrite content the target already has")
    args = ap.parse_args()

    base = Path(get_settings().storage_base_path)
    local = await connect(get_settings().database_url, remote=False)
    ws = await local.fetchrow("SELECT id, name FROM workspaces WHERE name = $1", args.workspace)
    if not ws:
        print(f"No connection called {args.workspace!r} here.")
        return 1
    rows = await local.fetch("SELECT entity_id, yaml_path, content FROM entity_profiles WHERE workspace_id = $1",
                             ws["id"])
    profiles, missing = {}, []
    for r in rows:
        if not r["entity_id"].split(":")[1:2] == [ws["name"]]:
            continue  # never anything outside this connection
        text = r["content"]
        if not text:
            f = base / r["yaml_path"]
            text = f.read_text(encoding="utf-8") if f.exists() else None
        if text:
            profiles[r["entity_id"]] = text
        else:
            missing.append(r["entity_id"])
    print(f"{ws['name']}: {len(profiles)} profiles to copy" + (f", {len(missing)} with no file" if missing else ""))

    target = await connect(args.to, remote=True) if args.to else local
    has_column = await target.fetchval(
        "SELECT 1 FROM information_schema.columns WHERE table_name = 'entity_profiles' AND column_name = 'content'")
    if not has_column:
        print("The target has no entity_profiles.content yet: deploy the new API there first (it migrates on start).")
        return 1
    guard = "" if args.force else " AND content IS NULL"
    updated = 0
    for eid, text in profiles.items():
        status = await target.execute(f"UPDATE entity_profiles SET content = $1 WHERE entity_id = $2{guard}", text, eid)
        updated += int(status.split()[-1])
    print(f"Updated {updated} profiles in the {'target' if args.to else 'local'} database.")
    await local.close()
    if args.to:
        await target.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
