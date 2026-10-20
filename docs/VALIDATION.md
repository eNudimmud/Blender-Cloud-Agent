# Validation record — 2026-10-20

Baseline inspected: `e6fc08d51297d84e465633df27116356a95922c1` on `main`, with the preceding primitive-generation/mobile prototype commits. The three latest baseline GitHub Actions runs failed during pytest collection (`ModuleNotFoundError: No module named 'app'`). The new repository package markers, pytest `pythonpath` and `python -m pytest` invocation fix that failure.

## Executed in the development environment

| Check | Observed result | Meaningful limits |
| --- | --- | --- |
| Python suite with `BLENDER_BIN` | 88 passed; no skips or warnings | Python 3.12.14, Linux x86_64; does not prove container isolation |
| Real Blender integration | All 5 passed | Official Blender 4.5.3 LTS archive, SHA-256 checked; CPU rendering |
| Real outputs | `.blend`, GLB v2, PNG 640×480, byte counts and hashes checked | Primitive scenes only; no animation/rigging/imported assets |
| Persistence | API recreated over the same data path; project, chat, scene version and queued job retained | Local filesystem SQLite, not remote cloud database |
| Worker lifecycle | Atomic concurrent claim, obsolete attempt rejection, stale lease failure, cancellation, timeout and partial-output cleanup passed | Failure-process fixtures test lifecycle; the five integration cases use real Blender |
| Authentication | Bearer/cookie access, tampering, CSRF/Origin refusal, login limit, token redaction, body bounds, authenticated files and symlink refusal passed | One owner, not multi-user authorization |
| Conversation | FR/EN primitive creation, recolor, position, size, removal, limits, proposal review/confirm/idempotency/conflicts passed | Deterministic grammar by default |
| External planner | Mock HTTP success, invalid scene/code fields, oversized response and disabled-spending zero-call gate passed | No actual LLM request, model quality, provider credits or billing tested |
| Playwright Chromium | 17 passed; 1 intentional desktop skip of the touch-only test | 9 Android/Pixel 7 emulation checks, 8 desktop checks |
| Touch viewer | Real synthetic touch orbit and two-touch pinch changed rendered screenshots | Emulated touch, not a physical phone/GPU certification |
| Mobile UI | Full real-render/download/reload path, offline request replay, 320 px layout, inert text handling and real PNG fallback passed | No runtime third-party asset requests in the tested path; offline creation/render execution is not supported |
| Runtime Python dependency audit | No known vulnerabilities reported after updating FastAPI/Starlette and pinning resolved runtime dependencies | Snapshot audit, not a security guarantee |
| Production npm audit | No known vulnerabilities reported | Production scope only; no development-dependency audit claimed |
| Ruff / JS syntax / viewer build | Passed | Not an exhaustive product usability assessment |

Blender archive checksum: `975c58fcb244273838534bba771e64ad87739216b0f9b39a888531a49a72d845`. The code asserts the tested Blender version in integration tests rather than silently accepting another binary.

The test suite found and corrected: missing package imports in baseline CI; synchronous API execution; nonpersistent projects; duplicate-submission risk; stale-proposal overwrites; lost input while switching projects; overflow at 320 px; viewer fallback behavior; and the earlier vulnerable Starlette pin. Inputs are locked during a mutating action so a delayed project load cannot erase an in-progress rename.

## GitHub Actions verification

The `MVP validation` workflow has two independent standard Linux jobs:

- `checks`: pinned Python runtime, production dependency audits, lint/build, real Blender executions, and both browser profiles. Reports/traces are uploaded for seven days.
- `containers`: build both real Docker targets, run Compose with hardening, inspect UID/read-only root/capabilities/no-new-privileges/PID/CPU/RAM/no-socket/no-worker-credentials/no-worker-network properties, render and download a real scene, restart API+worker, and verify the stored project/job/artifacts again.

Docker is not available in the local execution environment, so no local Docker success is claimed. Consult the linked GitHub Actions run/PR checks for the actual container-job outcome and exact commit SHA. The CI smoke data is ephemeral and removed at the end; no cloud hosting is created.

## Mobile portability and HTTPS follow-up

The local expanded suite passes 88 Python tests and 17 browser tests (one desktop-only touch skip). New checks cover feminine French colors, malformed coordinates, contradictory requests, portable-project round trips/idempotency/limits, trusted proxy address handling, exact origin validation and exclusive/private deployment configuration creation. The browser path covers file download/import, malformed or oversized imports, a server-committed request whose response is lost, manual retry without duplication, and viewport changes 344→822→393 px. Imports preserve scene data in a new project and create no render jobs.

The HTTPS overlay and CI smoke checks are included; use the current PR/run outcome before claiming they passed. The `containers` job now also builds a pinned Caddy proxy, validates the production deployment configuration without contacting an ACME service, tests TLS against a generated local CA, and runs the same browser profiles against the actual HTTPS API/Blender containers. This does not validate a public host or physical Android device. Baseline real-container/restart validation passed at commit `e042f396832f2a5e49cfe80db593c4a1d83de810`, run [39415092641](https://github.com/eNudimmud/Blender-Cloud-Agent/actions/runs/39415092641).

## Still pending

Physical Android and foldable-device acceptance; public HTTPS hosting and a publicly trusted certificate; real external LLM quality/billing tests (requires explicit authorization); native U*TTU import/mapping; an MCP adapter; arbitrary assets, richer scene operations, animation, GPU rendering, multiple owners and stronger per-job/per-tenant isolation. A PWA manifest is supplied, but offline service-worker operation and installation prompts have not been validated.
