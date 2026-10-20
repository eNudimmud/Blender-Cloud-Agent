# Blender Cloud Agent — Technical Alpha

Mobile-first cloud Blender automation project. Initial milestone: deterministic Blender scene generation API (no LLM, GPU or paid provider).

## Run locally

```bash
docker build -t blender-cloud-agent .
docker run --rm -p 127.0.0.1:8000:8000 blender-cloud-agent
```

```bash
curl -X POST http://127.0.0.1:8000/v1/scenes -H 'Content-Type: application/json' -d '{"shape":"cube","size":2}'
```

The response returns links to `scene.blend`, `scene.glb`, and `preview.png`. Shapes: cube, sphere, cylinder.

## Limitations and safety

**Local-only technical alpha; do not expose publicly.** This implementation is synchronous, has no authentication, queue, persistent database, mobile interface or resource quotas. Blender runs as a subprocess in the API container, **not** in a dedicated sandbox. A production deployment requires isolated workers, authentication, persistent jobs and limits. Blender is installed from the Debian package; pinning and compatibility validation are pending. The container build and end-to-end Blender generation have not yet been verified in CI.

## Roadmap

1. Worker isolation, durable jobs and artifact manifests.
2. React mobile PWA and touch GLB viewer.
3. Typed scene edits, versions and rollback.
4. Optional LLM planner and MCP-for-Blender adapter.
5. U*TTU Studio API integration.

## Mobile UI (new)

Open `http://127.0.0.1:8000/` after starting the container to access the mobile-first prototype. The interface provides a touch GLB viewer, a simple shape creation form, and artifact downloads. The Three.js modules currently load from a public CDN, so the viewer needs Internet access.

This is **not** yet a deployed Android-accessible service. For remote phone access, first add authentication, rate limits, isolated execution, and HTTPS. Do not publish the current unauthenticated API.

## Automated checks

`pytest -q` runs API smoke tests (install `pytest httpx` alongside requirements). GitHub Actions runs these checks on push and pull request. Blender generation itself still requires a Docker/Blender integration test.
