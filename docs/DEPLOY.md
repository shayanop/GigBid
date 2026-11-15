# Deploying the public demo

The public demonstration instance (spec E6) runs as a free **Hugging Face Docker Space**.
A Render Blueprint is kept as a paid alternative ([below](#alternative-render-about-38-a-month)).
`docker compose up` remains the full local stack ([RUNBOOK.md](RUNBOOK.md)).

## Hugging Face Space (free)

**Why.** The backend needs about 700 MB at idle, more than any free Render plan gives (512 MB).
A free CPU Space gives 2 vCPU and 16 GB of RAM in one container, which is enough for the
whole stack.

**What runs.** [`infra/hf/Dockerfile`](../infra/hf/Dockerfile) builds one image, and
[`infra/hf/start.sh`](../infra/hf/start.sh) starts these in the container:
- Postgres and Redis on localhost;
- the Next.js web app on port 7860, the Space's public port;
- the API on 8000, behind the web app's `/api` proxy;
- the worker, GigSim and the three MCP servers, through the same
  [`infra/render/start.sh`](../infra/render/start.sh) as on Render.

If any process exits, the container exits and the Space restarts it.

**Trade-offs of the free tier.**
- **No persistent disk.** The database lives in `/tmp`, so a restart resets it and the start
  script re-seeds the demo account. To keep data, create a free external Postgres (for
  example Neon) and set it as the `DATABASE_URL` secret; the script then skips the local
  one. `REDIS_URL` works the same way.
- **Sleeps.** A free Space sleeps after 48 hours without visitors. The first visit after
  that waits for it to start again, about a minute.
- **Public files.** A public Space shows its files. The push script sends only what git
  tracks (never `.env`, `data/raw` or `data/processed`) and leaves out `evals/`, `tests/`
  and `docs/`.

### Steps

1. Create a Hugging Face account and a **write** access token.
2. Log in and push:

   ```bash
   uv run hf auth login
   ```

   ```bash
   uv run python infra/hf/push.py <your-username>/gigbid
   ```

   The script creates the Space if needed. It uploads in one commit, so there is one
   build, and [`infra/hf/README.md`](../infra/hf/README.md) becomes the Space card.
3. In the Space's **Settings > Variables and secrets**, add these secrets:
   - `GROQ_API_KEY`: the default `open` profile uses Groq only;
   - `DEMO_EMAIL` and `DEMO_PASSWORD`: the demonstration login;
   - optional: `CEREBRAS_API_KEY` with the variable `GIGBID_PROFILE=cerebras`, to spread
     load over both providers ([RUNBOOK.md](RUNBOOK.md));
   - optional: `DATABASE_URL` for data that survives restarts;
   - optional: `PHOENIX_COLLECTOR_ENDPOINT` and `OTEL_EXPORTER_OTLP_HEADERS` for traces.

   `SESSION_SECRET` and `MCP_SIGNING_SECRET` are generated on each start when not set.
4. Wait for the build to finish (several minutes, because the image bakes the indexes),
   then open `https://<your-username>-gigbid.hf.space` and sign in with the demo login.
   Use that direct URL. The huggingface.co page shows the app in an iframe, and browsers
   that block third-party cookies won't keep you signed in there.

**Cookies.** The image sets `COOKIE_SECURE=1` and `COOKIE_SAMESITE=none`, so the session
cookie also works inside Hugging Face's iframe when the browser allows it.

### Checked locally

On 2026-11-15 the image was built from `infra/hf/Dockerfile` (4.0 GB) and run the way a
Space runs it:
- one container, as uid 1000, with only port 7860 published;
- no `DATABASE_URL` or `REDIS_URL`, so Postgres and Redis ran inside;
- the scripted `fake` profile.

What happened:
- `/health` through the web app's proxy passed about 12 seconds after start, and the start
  script seeded the demo account.
- `/signin`, `/inbox` and `/onboarding` rendered. The session cookie was set with
  `SameSite=None; Secure`.
- Through `/api`, the demo login signed in and job `job_00012` ran to approval. Approving
  it submitted the proposal to GigSim.
- The container used 1.0 GB of memory.

Nothing was pushed to Hugging Face, because that needs the account owner.

## Alternative: Render (about $38 a month)

[`render.yaml`](../render.yaml) is a Render Blueprint with separate managed Postgres and Key
Value, and persistent data.

### What it creates

| Render resource | Plan | Runs |
| --- | --- | --- |
| `gigbid-backend` (web service, Docker) | Standard, 2 GB | [`infra/render/start.sh`](../infra/render/start.sh): API on `$PORT`, Arq worker, GigSim, Marketplace / Portfolio / Workspace MCP |
| `gigbid-web` (web service, Docker) | Starter | Next.js on `$PORT`, proxying `/api/*` to the backend over Render's private network |
| `gigbid-queue` (Key Value) | Free | Arq queue, private network only, `noeviction` |
| `gigbid-db` (Postgres) | Basic 256 MB | Users, threads, LangGraph checkpoints and store |

**The backend container.**
- **Why one container.** It runs the six Python processes of the compose stack together.
  On Render each separate worker or private service is billed on its own, and the demo
  needs none of them to scale independently.
- **Localhost only.** GigSim and the MCP servers listen on `127.0.0.1`, so only the API is
  reachable from outside. Every agent tool call still goes through MCP with a signed
  per-user token, exactly as in compose.
- **Restarts.** If any process exits, the container exits and Render restarts it. Approvals
  survive restarts through the outbox and orphan sweep ([ARCHITECTURE.md](ARCHITECTURE.md)).
- **Fast boot.** The image bakes in the embedding model and every persona's portfolio index
  (`infra/docker/python.Dockerfile`).

**Cost.** At Render's list prices this is about $25 for the Standard backend, $7 for the
Starter web app and $6 for the database, so roughly $38 a month. Check render.com/pricing
before creating it. The Key Value instance is free.

### Steps on Render

1. Push the repository to GitHub. Render deploys from a Git provider.
2. In the Render dashboard choose **New > Blueprint**, pick the repository and confirm
   `render.yaml`.
3. Fill the secrets Render asks for:
   - `GROQ_API_KEY` and `CEREBRAS_API_KEY`: the `cerebras` profile uses both.
   - `NIM_API_KEY`: optional; only the `nim` profile uses it.
   - `DEMO_EMAIL` and `DEMO_PASSWORD`: the demonstration login.

   `SESSION_SECRET` and `MCP_SIGNING_SECRET` are generated by Render.
4. Apply. The first build takes several minutes, because the backend image bakes the
   indexes. The web app builds against the backend's private address.
5. When `gigbid-backend` reports healthy (`/health` checks Postgres and Redis), open the
   `gigbid-web` URL and sign in with the demo login. The persona is the AI/ML freelancer,
   seeded with one saved search; the start script re-seeds it on every boot.

### Configuration notes

- **Model profile.** `GIGBID_PROFILE=cerebras` spreads nodes over Groq's and Cerebras'
  rate limits. On free tiers a busy demo still meets 429s ([RUNBOOK.md](RUNBOOK.md)). For a
  demo without keys, set `GIGBID_PROFILE=fake`: scripted, no cost.
- **Ephemeral files.** The marketplace audit log and the workspace mock write to
  `/tmp/gigbid` and are reset on each deploy. Everything that must survive is in Postgres.
- **GigSim data.** GigSim serves its synthetic marketplace. `GIGSIM_DATA=real` would need
  `data/processed/real/gigsim.jsonl` (100 MB, built by `data/real/prepare.py`), which is
  not in the repository or the image.
- **Cookies.** `COOKIE_SECURE=1`: Render serves HTTPS, and the session cookie is
  same-origin through the web app's proxy, so no CORS is needed.
- **Schema.** The API applies the schema with `CREATE IF NOT EXISTS` on startup; there are
  no migrations yet (`apps/api/db.py`).

### Checked locally on Render

On 2026-11-15 both images were built and run the way Render runs them:
- `PORT=10000`;
- the backend command was `infra/render/start.sh`;
- the web app was built with `API_URL` as a bare `host:port`;
- a separate database was used;
- the scripted `fake` profile was used.

What happened:
- All six backend processes started, and `/health` passed.
- The start script seeded the demo account.
- Through the web app's `/api` proxy, the demo login signed in and a job ran through the
  worker and MCP servers to approval. Approving it submitted the proposal to GigSim.
- The backend container used 674 MB at idle, which is why it is on Standard (2 GB) rather
  than Starter (512 MB).

This was not deployed to Render itself, because that needs the account owner.

**Building on a memory-tight machine.** Docker Desktop's VM crashed twice while baking the
index with all cores, when the host had under 3 GB free. The bake step now uses one thread
(`OMP_NUM_THREADS=1`).
