# Deploying Kairos + Jenny on Render

What gets deployed ([`render.yaml`](../render.yaml)):

| Render resource | What it is | Plan |
|---|---|---|
| `kairos-jenny-db` | Postgres 16 (with pgvector): the map, data products, Jenny's state | basic-1gb |
| `kairos-jenny-api` | The API (Docker, the root `Dockerfile`): Kairos and Jenny's brain | standard (2 GB), one instance, always on |
| `kairos-jenny-web` | The app (Next.js, `frontend/`) | starter |

Not deployed: Jenny's Google Meet body (`meet/`) — it needs a real browser signed in to Google, so on the hosted app
the Meet button explains that and points to the demo video — and the Kokoro voice (ElevenLabs is her voice).

## 1. Make a copy of the data that is safe to publish

With the local stack running (`docker compose up -d`):

```bash
bash deploy/make_public_db.sh
```

It copies your local database, removes the ICS Sales Warehouse connection and everything learned from it (plus its
agent activity and all evaluation runs), checks every text column for any trace left (it stops if one is), and writes
`kairos-public.dump`. Your working database is not touched. Re-run it whenever you want to refresh the deployed data.

## 2. Create the services

1. Push this repo to GitHub (a private repo is fine; Render only builds it).
2. Render dashboard → **New → Blueprint** → pick the repo. Render reads `render.yaml`.
3. Fill in the secrets it asks for:
   - `NEBIUS_API_KEY`
   - `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT` (embeddings; leave empty and search falls back to keywords)
   - `ELEVENLABS_API_KEY`, `TYPESAFE_API_KEY`
   - `TAVILY_API_KEY` (Jenny's weather lookup)
   - `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_TOKEN`, `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_ROLE` — use a
     **read-only** role
   - Never the `DATABRICKS_*` values from your local `.env`: they reach the ICS warehouse.
4. **Apply**. The first deploy takes a few minutes; the API creates an empty schema on its first start.
5. Check the two URLs Render gave the services. If they aren't exactly `kairos-jenny-api.onrender.com` and
   `kairos-jenny-web.onrender.com`, fix them in the API's `FRONTEND_ORIGINS`, `PUBLIC_API_URL`, `MCP_ALLOWED_HOSTS` and
   the web app's `NEXT_PUBLIC_API_URL`, `API_ORIGIN`, then redeploy both.

## 3. Load the data

Render → `kairos-jenny-db` → **Connect** → copy the **External Database URL**, then:

```bash
bash deploy/restore.sh "postgresql://kairos:...@dpg-....frankfurt-postgres.render.com/kairos"
```

Then restart the API: `kairos-jenny-api` → **Manual Deploy → Restart service**.

## 4. Check it

Open `https://kairos-jenny-web.onrender.com`:

- The starter guide opens by itself (in a fresh browser or a private window).
- **Overview** shows Zomato Snowflake, 29 tables. Nothing about ICS anywhere.
- **Jenny** shows her live pulse; ask her "How are we doing today?" in the chat.
- `https://kairos-jenny-api.onrender.com/health` answers.

## Before you share the link

- **Live data during judging (1–15 December).** Jenny's pulse reads the latest orders in Snowflake; if no new orders
  arrive she says "Not live". Keep the feed into Snowflake running through the judging period.
- **Spend.** Anyone with the link can start enrichment or the products engine (Nebius tokens, Snowflake compute) and
  talk to Jenny (ElevenLabs). Set a resource monitor on the Snowflake warehouse and spending limits on Nebius and
  ElevenLabs.
- **One API instance.** Keep `numInstances: 1`: her pulse, enrichment runs and calls live in that process.

## When something's wrong

| What you see | Look at |
|---|---|
| The app loads but every screen is empty, the console says CORS | The API's `FRONTEND_ORIGINS` must be the web app's exact URL, as a JSON list |
| The app calls `127.0.0.1` | `NEXT_PUBLIC_API_URL` wasn't set when the web app was built: set it, redeploy the web app |
| The API keeps restarting | Its logs: usually a missing secret, or the database URL |
| Jenny says "Not live" | No new orders in Snowflake recently: the feed |
