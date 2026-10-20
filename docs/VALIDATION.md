# Validation record — 2026-10-20

Baseline inspected: `e6fc08d51297d84e465633df27116356a95922c1` on `main`, with the preceding primitive-generation/mobile prototype commits. The three latest baseline GitHub Actions runs failed during pytest collection (`ModuleNotFoundError: No module named 'app'`). The new repository package markers, pytest `pythonpath` and `python -m pytest` invocation fix that failure.

## Executed in the development environment

| Check | Observed result | Meaningful limits |
| --- | --- | --- |
| Python suite with `BLENDER_BIN` | 52 passed; no skips or warnings | Python 3.12.14, Linux x86_64; does not prove container isolation |
| Real Blender integration | All 5 passed | Official Blender 4.5.3 LTS archive, SHA-256 checked; CPU rendering |
| Real outputs | `.blend`, GLB v2, PNG 640×480, byte counts and hashes checked | Primitive scenes only; no animation/rigging/imported assets |
| Persistence | API recreated over the same data path; project, chat, scene version and queued job retained | Local filesystem SQLite, not remote cloud database |
| Worker lifecycle | Atomic concurrent claim, obsolete attempt rejection, stale lease failure, cancellation, timeout and partial-output cleanup passed | Failure-process fixtures test lifecycle; the five integration cases use real Blender |
| Authentication | Bearer/cookie access, tampering, CSRF/Origin refusal, login limit, token redaction, body bounds, authenticated files and symlink refusal passed | One owner, not multi-user authorization |
| Conversation | FR/EN primitive creation, recolor, position, size, removal, limits, proposal review/confirm/idempotency/conflicts passed | Deterministic grammar by default |
| External planner | Mock HTTP success, invalid scene/code fields, oversized response and disabled-spending zero-call gate passed | No actual LLM request, model quality, provider credits or billing tested |
| Playwright Chromium | 9 passed; 1 intentional desktop skip of the touch-only test | 5 Android/Pixel 7 emulation checks, 4 desktop checks |
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

## Still pending

Physical Android and foldable-device acceptance; public HTTPS hosting and proxy verification; real external LLM quality/billing tests (requires explicit authorization); native U*TTU import/mapping; an MCP adapter; arbitrary assets, richer scene operations, animation, GPU rendering, multiple owners and stronger per-job/per-tenant isolation. A PWA manifest is supplied, but offline service-worker operation and installation prompts have not been validated.
