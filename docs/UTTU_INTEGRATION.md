# Future U*TTU Studio adapter

Blender Cloud Agent remains an independent single-owner service. No changes to U*TTU Studio are included here. `/openapi.json`, `/v1/schema/scene`, and `/v1/capabilities` describe the versioned API. Schema version 1 only supports up to 24 bounded cube/sphere/cylinder objects, with meter units and Blender Z-up coordinates. GLB exports are converted to glTF Y-up.

The Studio server keeps `API_TOKEN` in its secret store and calls this service with `Authorization: Bearer …`. Do not embed that token in Studio JavaScript, URLs, localStorage, GLB metadata, or prompts. No CORS is enabled: Studio must use its own backend, not direct cross-origin browser calls. An internet-facing deployment needs HTTPS and an exact `PUBLIC_ORIGIN` for the Agent's own mobile UI.

## Minimal flow

1. `GET /v1/capabilities`: show supported shapes, planner mode, and worker availability. A queued job with an offline worker is not a successful render.
2. `POST /v1/projects` with `Idempotency-Key` and `{name,scene}`: persist the local/IndexedDB scene explicitly. Store the returned server project ID in the Studio project mapping. The same request key and payload return the same project and object IDs.
3. `POST /v1/projects/{id}/chat` with a unique request key and `{message}`: prepare an inert scene proposal. Display its actual object values/diff. In guided mode only the documented grammar is supported; the external LLM adapter is disabled by default.
4. After the user chooses to execute, `POST /v1/projects/{id}/proposals/{proposalId}/confirm`: atomically save the new project revision and queue one render. Confirmation is idempotent. A stale proposal returns 409, a full queue 429; neither partially changes the project.
5. Alternatively, `PUT /v1/projects/{id}` with `{name,scene,revision}`, then `POST /v1/projects/{id}/jobs` with `{revision}` and a unique request key. A conflict requires retrieving the project again.
6. Poll `GET /v1/jobs/{jobId}` with backoff, stop while the Studio tab is hidden, and resume on return. Persist project/job IDs before awaiting completion. Terminal states are `succeeded`, `failed`, and `cancelled`.
7. When `succeeded`, download authenticated files and verify SHA-256/size against `artifacts`. Copy the GLB/PNG into the Studio's own storage with provenance `{projectId,jobId,revision,sha256,blenderVersion}`. Do not treat temporary client blob URLs as persisted assets.
8. `POST /v1/jobs/{jobId}/cancel` cancels queued work immediately; a running worker terminates its Blender process group when it observes cancellation. No automatic render retry after a lost worker.

Idempotency keys: 8–100 ASCII letters/digits/underscores/hyphens; UUIDs are suitable. Retain a key across retries of the same action; generate a new key for an intentional new action. HTTP 202 means queued, not completed. Artifact links are same-service relative paths and require authentication. Rate limits apply to the shared single-owner workspace.

## Integration acceptance still pending

Real Studio project mapping, IndexedDB-to-server transfer, permissions, artifact import, browser routing, and user acceptance tests must be implemented and validated in U*TTU. This repository supplies the backend contract; it does not claim an end-to-end Studio integration or multi-user identity federation.

## Portable project exchange

`GET /v1/projects/{id}/export` returns an authenticated `.bca.json` attachment (`format=blender-cloud-agent/project`, `format_version=1`). `POST /v1/projects/import` accepts that envelope plus an idempotency key and creates a new project without rendering or overwriting the source. The optional `source` metadata preserves provenance only, not write authority. Scene object IDs are retained. This offers an explicit transfer boundary for a future Studio importer, but does not contain artifacts/history or replace the Studio asset-storage import step.
