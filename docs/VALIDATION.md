# Validation record — 2026-10-20

Baseline inspected: `e6fc08d51297d84e465633df27116356a95922c1` on `main`, with the preceding primitive-generation/mobile prototype commits. The three latest baseline GitHub Actions runs failed during pytest collection (`ModuleNotFoundError: No module named 'app'`). The new repository package markers, pytest `pythonpath` and `python -m pytest` invocation fix that failure.

## Executed in the development environment

| Check | Observed result | Meaningful limits |
| --- | --- | --- |
| Python suite with `BLENDER_BIN` | 107 passed; no skips or warnings | Python 3.12.14, Linux x86_64; does not prove container isolation |
| Real Blender integration | All 5 passed | Official Blender 4.5.3 LTS archive, SHA-256 checked; CPU rendering |
| Real outputs | `.blend`, GLB v2, PNG 640×480, byte counts and hashes checked | Primitive scenes only; no animation/rigging/imported assets |
| Persistence | API recreated over the same data path; project, chat, scene version and queued job retained | Local filesystem SQLite, not remote cloud database |
| Worker lifecycle | Atomic concurrent claim, obsolete attempt rejection, stale lease failure, cancellation, timeout and partial-output cleanup passed | Failure-process fixtures test lifecycle; the five integration cases use real Blender |
| Authentication | Bearer/cookie access, tampering, CSRF/Origin refusal, login limit, token redaction, body bounds, authenticated files and symlink refusal passed | One owner, not multi-user authorization |
| Conversation | FR/EN primitive creation, recolor, position, size, removal, limits, proposal review/confirm/idempotency/conflicts passed | Deterministic grammar by default |
| External planner | Mock HTTP success, invalid scene/code fields, oversized response and disabled-spending zero-call gate passed | No actual LLM request, model quality, provider credits or billing tested |
| Playwright Chromium | 25 passed; 1 intentional desktop skip of the touch-only test | 13 Android/Pixel 7 emulation checks, 12 desktop checks |
| Explicit object selection | Targeted edits affect the selected ID; spec and real GLB picks, reload persistence, orbit/pinch refusal and mock LLM cross-object refusal passed | Selection uses saved scene IDs; unsupported shape combinations return guidance |
| Saved project history | Preview, restore without rendering, concurrent conflict/replay, pruning to 100 versions and atomic quota rollback passed | Name/scene snapshots; not a full artifact/conversation backup; 2,000 restore receipts per workspace |
| Database upgrade | Four independent Python processes concurrently migrated the pinned v1 fixture; existing project, pending job and legacy proposal retry retained | Linux local filesystem; only the current pre-upgrade revision is backfilled |
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

The preceding MVP passed both jobs at merged commit `0a322733d09a9a2838416300bbf13a017b939f81` in [run 39470070262](https://github.com/eNudimmud/Blender-Cloud-Agent/actions/runs/39470070262). Its `checks` job passed all 88 Python tests and 17 browser tests; `containers` independently passed the real Docker/render/restart smoke checks, verified TLS with the test CA, and passed the same 17 browser tests over HTTPS. Each browser run has one intentional desktop skip for the touch-only case. Reports are retained for seven days; job logs and the pinned commit identify that baseline.

The selection/history follow-up expands the local results above to 107 Python and 25 browser passes. Its workflow repeats both browser profiles in HTTP and actual HTTPS containers, and the container smoke now restores a version before restarting API/worker, checks persisted history, stale proposal refusal and retained older artifacts. The follow-up PR records its own final CI run/SHA; the earlier run above must not be used as evidence for the newer features.

Docker is not available in the local execution environment, so container validation was performed by GitHub Actions. The CI smoke data is ephemeral and removed at the end; no cloud hosting was created.

## Mobile portability and HTTPS follow-up

The preceding portability/HTTPS stage passed 88 Python tests and 17 browser tests (one desktop-only touch skip). Those checks cover feminine French colors, malformed coordinates, contradictory requests, portable-project round trips/idempotency/limits, trusted proxy address handling, exact origin validation and exclusive/private deployment configuration creation. The browser path covers file download/import, malformed or oversized imports, a server-committed request whose response is lost, manual retry without duplication, and viewport changes 344→822→393 px. Imports preserve scene data in a new project and create no render jobs. The selection/history additions bring the local totals to 107 and 25 respectively, as recorded above.

The passing `containers` job builds a pinned Caddy proxy, validates the production deployment configuration without contacting an ACME service, tests TLS against a generated local CA, and runs the same browser profiles against the actual HTTPS API/Blender containers. It verifies secure cookies, exact-origin refusal, spoofed-address refusal, private API ports and portable-project transfer. HTTP/3 is disabled because only TCP is published. The official image's binary file capability initially prevented startup with all capabilities dropped; removing that file capability allowed the non-root proxy to execute on unprivileged ports, and the final container check confirms it is absent. This does not validate a public host or physical Android device. Earlier baseline real-container/restart validation passed at commit `e042f396832f2a5e49cfe80db593c4a1d83de810`, run [39415092641](https://github.com/eNudimmud/Blender-Cloud-Agent/actions/runs/39415092641).

## Still pending

Physical Android and foldable-device acceptance; public HTTPS hosting and a publicly trusted certificate; real external LLM quality/billing tests (requires explicit authorization); native U*TTU import/mapping; an MCP adapter; arbitrary assets, richer scene operations, animation, GPU rendering, multiple owners and stronger per-job/per-tenant isolation. A PWA manifest is supplied, but offline service-worker operation and installation prompts have not been validated.

Browser profiles use separate ephemeral API lifecycles for direct-HTTP tests. In the shared HTTPS CI stack, only the test workspace's rate counters are reset between profiles, guarded by the known CI-only access key. This prevents the automated suites from consuming each other's per-workspace quota; production limits remain unchanged and are tested in the API suite. File-picker tests wait for the input to become enabled after startup/reload, matching an actual user interaction.

The version-history tests also found and corrected a simultaneous WAL initialization failure. A same-host OS lock now covers journal setup and the transactional schema migration. Restarts and migration preserve existing data; the prior API version deliberately refuses the new schema, so reverting an upgrade requires compatible code or the pre-upgrade backup. See [mobile editing and upgrade boundaries](MOBILE_EDITING.md).
