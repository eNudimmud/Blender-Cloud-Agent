# Blender Cloud Agent — Mobile MVP

A personal 3D workspace operated from an Android browser. Blender runs on the server; the phone needs no Blender installation, GPU, terminal, or API key for an AI provider.

The MVP supports bounded primitive scenes, persistent projects, conversational proposals, touch previews, asynchronous CPU rendering, and authenticated `.blend` / `.glb` / PNG downloads. It is a **single-owner workspace**, not a public multi-tenant service or an unrestricted text-to-3D generator.

[View the tested Android interface](docs/images/android-workspace.webp)

## What works

- Save and rename projects; keep scene revisions, render snapshots, job status and conversation in SQLite on a persistent volume.
- Add cubes, spheres and cylinders; change color/size/position or remove an object through the guided FR/EN assistant. Review actual proposed values, preview locally in 3D, then confirm to save and render.
- Orbit with one finger, pinch to zoom, and pan with two fingers. Three.js is bundled and served by the API; no CDN requests at runtime. Show the real PNG and download links when WebGL is unavailable.
- Queue jobs without blocking the API. Claim jobs transactionally, cancel queued/running work, enforce deadlines, fence obsolete workers and publish only complete artifacts with SHA-256 manifests.
- Export a portable `.bca.json` on Android and import it into a new copy; importing never overwrites the original or launches a render.
- Recover the selected project after a reload. Retain a pending action's request key in the browser session and replay it safely after reconnection/reload or using **Reprendre l’envoi**. Ambiguous external-LLM planning requests require a manual retry. Projects and jobs survive server restarts.
- Run the API without Blender and the worker in a separate non-root container: no network, read-only root, no capabilities or Docker socket, 2 CPU / 2 GiB / 128 PID limits, bounded tmpfs. One Blender process per worker at a time.
- Authenticate with a private workspace key and an HttpOnly, SameSite cookie; support bearer authentication for a future U*TTU backend adapter.

## Validation

On 2026-10-20: **88 Python tests passed**, including five executions of real Blender 4.5.3 LTS (cube, sphere, cylinder, combined scene and empty scene). **17 browser tests passed**, with 1 intentional skip for a touch-only test in the desktop profile. Android is Chromium/Pixel 7 emulation, including real touch-event orbit/pinch, not a physical-device certification. Narrow 320 px layout, foldable viewport changes, lost-response recovery, portable project export/import, restart persistence, artifact access and the PNG fallback are covered.

Runtime Python dependencies were updated after auditing the earlier Starlette pin. The final local Python and production npm audits reported no known vulnerabilities. Docker is unavailable in the development environment; the dedicated GitHub Actions `containers` job builds the service images, verifies the configured isolation, renders a real scene, checks restart persistence, and exercises the HTTPS proxy and browser path with a local test certificate. Its actual run is the authority for container validation.

See [the detailed validation record](docs/VALIDATION.md) and [GitHub Actions](https://github.com/eNudimmud/Blender-Cloud-Agent/actions). Passing tests do not mean this service is already hosted or physically tested on Android.

## Start on an existing server

These are **server/operator commands**, not instructions for the Android user. The validated image target is Linux x86_64 with Docker Compose v2.

```bash
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_urlsafe(36))'
# Put the generated key into API_TOKEN in .env.
docker compose build
docker compose up -d --wait
```

For a developer using HTTP on the server's own localhost, set `COOKIE_SECURE=false` and open `http://127.0.0.1:8000`. By default the API binds only to server loopback and cookies require HTTPS.

For Android access, use the tested [HTTPS deployment package](docs/HTTPS_DEPLOYMENT.md): `python3 scripts/deploy.py init --hostname your-host.example`, then `check` and `up` on an existing server. It generates private keys, sets the exact origin and secure cookies, and puts a pinned Caddy proxy in front of the private API. Open that HTTPS address on Android and enter the workspace key once. The worker exposes no port. No hosting account, paid VM, GPU, external AI request or deployment is provisioned by this repository.

The named `agent-data` volume holds `agent.sqlite3` and `artifacts/`. It survives ordinary stop/restart/rebuild operations. Keep the same Compose project name and back up the complete volume while both services are stopped. `docker compose down -v` deletes that data; it is used only to clean up ephemeral CI data. Existing artifacts produced by the old `/v1/scenes` alpha are not automatically imported.

## Guided conversation examples

```text
Ajoute un cube rouge de taille 2
Ajoute une sphère bleue x=3
Change la couleur du cube en vert
Déplace le cube x=-2 y=0 z=1
Change sa taille à 3,5
Supprime la sphère
```

One action per message. A shape name targets the last matching object; an implicit target uses the last object. Unsupported requests return guidance instead of executing anything. Names and proposed object values can be inspected before confirmation. Rendering an empty scene is supported.

## Optional external AI

Default: `AGENT_MODE=rules`, `ALLOW_PAID_AI=false`. This is a deterministic conversational assistant, **not an active LLM**. No inference credits are consumed.

The optional `llm` planner accepts a trusted operator-configured HTTPS Chat Completions-compatible endpoint (`LLM_URL` ending in `/chat/completions`, `LLM_MODEL`, `LLM_API_KEY`). It returns only the same strictly validated scene JSON. It has no code tools, filesystem access, render authority, or worker credentials. External planning requires both `AGENT_MODE=llm` and explicit `ALLOW_PAID_AI=true`. Do not enable spending without the owner's authorization. No such authorization was used during this implementation.

The adapter is validated with mock HTTP responses only, including malicious/oversized responses and the zero-network spending gate. No live provider, model quality, billing ceiling, or exactly-once billing across crashes is validated. A confirmed render is a separate action from the potentially billable planning call.

## API and repository

```text
app/
  main.py       Authenticated FastAPI routes; API never starts Blender
  models.py     Strict version-1 scene and API response schemas
  store.py      SQLite transactions, idempotency, worker leases, quotas
  agent.py      Guided planner + disabled external planner adapter
  security.py   Signed sessions, CSRF checks and streamed body bound
  static/       Mobile UI and locally served assets
frontend/       Three.js touch viewer source; build output is ignored
worker/
  runner.py     Offline queue consumer and process lifecycle
  generate.py   Fixed trusted headless Blender script; no generated Python
scripts/        Checksum-pinned Blender install and Compose smoke checks
tests/          API, worker, real Blender, planner and browser coverage
docs/           Architecture, validated scope, MCP study and U*TTU contract
```

API schema: `/openapi.json`, scene schema: `/v1/schema/scene`, current capabilities: `/v1/capabilities`. Mutating project/chat/render requests use `Idempotency-Key`; revision conflicts return 409. The old synchronous `/v1/scenes` endpoint has been replaced by the asynchronous project/job API.

- [HTTPS deployment and portable project recovery](docs/HTTPS_DEPLOYMENT.md)
- [Architecture and security boundaries](docs/ARCHITECTURE.md)
- [MCP-for-Blender assessment](docs/MCP_INTEGRATION.md): upstream explicitly refuses background mode and exposes arbitrary Python; it is not installed in this MVP.
- [Future U*TTU Studio integration](docs/UTTU_INTEGRATION.md): server-side bearer adapter; no Studio repository modified.

## Developer checks

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
npm ci --ignore-scripts
npm run build
.venv/bin/ruff check app worker tests scripts
.venv/bin/python -m pytest -q
bash scripts/install_blender.sh /tmp/bca-blender
BLENDER_BIN=/tmp/bca-blender/blender-4.5.3-linux-x64/blender .venv/bin/python -m pytest -q
npx playwright install --with-deps chromium
BLENDER_BIN=/tmp/bca-blender/blender-4.5.3-linux-x64/blender npm run test:e2e
.venv/bin/pip-audit -r requirements.txt --no-deps --disable-pip
npm audit --omit=dev
```

Without `BLENDER_BIN`, five real-Blender tests and the real-render browser cases skip explicitly. Running the Python worker directly is a developer harness, not OS isolation; production isolation is provided by Compose.
