# HTTPS deployment on an existing server

This package does not provision a VM, create a hosting account, modify DNS, or enable a paid provider. It runs on an existing Linux x86_64 server with Docker Compose 2.24+ and a public hostname. The Android user only opens the final HTTPS address and enters the workspace key; all commands here belong on the server.

## First deployment

```bash
python3 scripts/deploy.py init --hostname blender.example.com
python3 scripts/deploy.py check
python3 scripts/deploy.py up
```

Replace `blender.example.com` with a hostname you control and point its DNS record at the server. Public TCP ports 80 and 443 must reach this server. `init` creates `.env` privately (mode 0600), with separate random workspace/proxy secrets, exact public origin, secure cookies and external AI disabled. It refuses to overwrite an existing file. Retrieve the workspace key privately on the server; do not paste it into an issue, browser URL or chat. The helper never prints keys or resolved environment configuration.

`check` validates the actual merged Compose configuration: matching hostname/origin, private API port, separate matching proxy keys, secure cookies, isolated worker and no service credentials in that worker. `up` repeats the preflight then builds/starts the stack. These operations do not acquire a host for you.

For an existing `.env`, retain the original workspace key and data volume; add the following fields with a separate private proxy key instead of recreating the file:

```dotenv
BCA_HOSTNAME=blender.example.com
PUBLIC_ORIGIN=https://blender.example.com
PROXY_SHARED_KEY=<a separate random value of at least 32 characters>
COOKIE_SECURE=true
AGENT_MODE=rules
ALLOW_PAID_AI=false
```

The generated/edited file stays on the server. `.env` and `.env.*` are ignored by git. Set `PROXY_SHARED_KEY` to a random value, not the placeholder above.

## What the overlay changes

`compose.https.yml` adds a pinned Caddy 2.11.7 proxy. Only that proxy publishes host ports. The API's existing loopback port is removed with Compose's `!reset`, and the worker still has no network or exposed port. Caddy runs as UID/GID 10001, with a read-only root, dropped capabilities, no-new-privileges and bounded RAM/CPU/PIDs/tmpfs. Only its TLS/config volumes are writable.

Caddy listens internally on unprivileged ports 8080/8443, mapped externally to 80/443. The image removes the upstream binary’s bind-service file capability, so it can execute with all container capabilities dropped. A loopback HTTPS health probe checks liveness; it accepts the local test certificate for that probe only, while the independent TLS test verifies the chain and hostname. Public hostname configuration requests and renews a normal public TLS certificate. The Caddy admin API and config persistence are disabled. Its certificate storage remains persistent in the `caddy-data` volume. See the primary [automatic HTTPS documentation](https://caddyserver.com/docs/automatic-https) and [Compose reset semantics](https://docs.docker.com/reference/compose-file/merge/#reset-value).

The proxy replaces incoming client-IP/proxy-auth headers with its own values. The API accepts that client address only when the proxy authenticates it with the shared secret; arbitrary `X-Forwarded-For` is ignored. This preserves per-address login limits without trusting browser-supplied IPs. Uvicorn proxy-header inference stays disabled. Origin checks use the exact configured HTTPS origin.

HTTP/1.1 and HTTP/2 are enabled. HTTP/3 advertisement is disabled because this overlay publishes TCP only, so clients are not directed to an unpublished UDP service. HSTS is enabled for this hostname only. No wildcard/subdomain policy is imposed. This does not supply a WAF, organizational login, DDoS service or per-tenant sandbox.

## Stop, update and recover

Use the same Compose project name, `.env` and overlay for future operations:

```bash
docker compose -f compose.yml -f compose.https.yml ps
python3 scripts/deploy.py up
docker compose -f compose.yml -f compose.https.yml stop
```

Back up the entire `agent-data` volume while API and worker are stopped for a complete database/artifact copy. Preserve `caddy-data` for certificates as well. Normal stop/restart/rebuild keeps these named volumes. Do not use `down -v` on a real workspace. Automatic backups, encrypted off-host storage and backup rotation are still operator responsibilities.

From Android, **Exporter le projet** downloads a portable `.bca.json` containing the saved project name and declarative scene. **Importer un projet** creates a new copy, preserving its object IDs and values. The original is not overwritten and no render/provider request is triggered by import. This is a project transfer/recovery format, not a full server backup: it excludes conversation history, job states, `.blend`/GLB/PNG files and credentials. Download rendered files separately or preserve the full server volume.

## CI evidence and remaining boundary

CI first tests the isolated Blender services and restart persistence. It then starts the actual proxy overlay using `deploy/compose.test.yml`, which switches only the certificate issuer to a local test CA. `scripts/https_smoke.py` loads that public CA certificate and verifies TLS normally; it checks HTTP→HTTPS redirects, secure HttpOnly cookies, Origin/CSRF refusal, spoofed address refusal, private API ports and portable project transfer. The browser suite also runs against those real HTTPS containers and their Blender worker.

These checks passed in [run 39468862491](https://github.com/eNudimmud/Blender-Cloud-Agent/actions/runs/39468862491), commit `894f644430d37a39122ccb6d50631a76f4d639ed`: both CI jobs succeeded, including 17 browser passes over HTTPS and one intentional desktop touch skip. See [the validation record](VALIDATION.md) for the exact scope and fixture isolation.

Chromium's HTTPS test profile accepts the local test certificate; Python independently validates its hostname/chain against the generated CA. No public ACME certificate, DNS change or external deployment is claimed by this test. `deploy/tls.internal.caddy` and `deploy/compose.test.yml` are CI fixtures and must not be used for the Android deployment. Android production needs the public configuration and a publicly trusted certificate; do not install the CI root CA on a user's phone.

The resolved Compose configuration contains secrets. Use the helper or `docker compose config --quiet` to validate it, and do not publish the raw output. The public deployment itself still needs an existing server, DNS and access authorization; none has been connected or provisioned by this change.
