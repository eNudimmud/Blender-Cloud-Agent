# Precise mobile editing and project history

## Choose the object before editing

In the current saved scene, tap a mesh or use **Objet à modifier**. The list includes names, short IDs and positions, so two cubes with identical names can be distinguished. A gold box marks the selected 3D object. The same object ID is carried in the real Blender GLB's extras. The list works even if the browser falls back to the PNG.

Orbit drags, multi-touch gestures and long presses do not select objects. Tap empty space or choose automatic targeting to clear the selection. A selection is retained in the current browser session and restored only if the same project still contains that ID. A removed object cannot become an implicit selection of another object.

Requests such as **Change sa couleur en vert**, **Déplace-le x=2** and **Supprime cet objet** target the selected ID. Adding a new primitive keeps the existing objects. A named shape that contradicts the selected object's shape is refused. Automatic mode retains the previous last-matching-object behavior.

Proposed scenes, saved historical scenes and older render previews are read-only: editing, renaming and rendering controls are disabled. Use **Revenir au projet actuel** to continue editing the saved scene, or explicitly confirm the displayed proposal/restoration. This prevents edits based on the wrong visible version. Merely selecting an object or inspecting history makes no server mutation or paid request.

## Examine and restore a saved version

Open **Historique du projet**, choose a version, then **Examiner cette version**. The preview shows that saved scene; the review text shows its name and explains the resulting new revision. **Confirmer la restauration** copies that name/scene into a new revision without starting Blender. Current snapshots are not restored into themselves. Returning to the current project cancels the review.

A restore does not cancel existing jobs or overwrite their artifacts. Old proposals become stale because the current revision changes. A queued render continues using its immutable original snapshot. To produce new files after restoration, explicitly launch a new render from the current project.

The last 100 snapshots per project are retained. Creation/import, rename/direct scene update, confirmed conversation and restore save snapshots in their transaction. Rendering an unchanged version does not add a snapshot. Restores are limited to 2,000 replay receipts per workspace; retries of a successful receipt remain available at that limit. This history is not a backup of conversations, files or the complete server volume. Portable JSON export still contains only the current saved name/scene.

## HTTP contract

| Operation | Request | Result |
| --- | --- | --- |
| Prepare a targeted edit | `POST /v1/projects/{id}/chat`, idempotency key, `message`, displayed `revision`, optional `object_id` | A typed proposal; no render |
| List saved versions | `GET /v1/projects/{id}/versions` | Up to 100 summaries; no scene bodies |
| Inspect one version | `GET /v1/projects/{id}/versions/{revision}` | Saved scene/name, reason and restore provenance |
| Restore after review | `POST /v1/projects/{id}/restore`, idempotency key, `revision`, `source_revision` | A new saved project revision; no job/provider call |

Authentication and cookie CSRF/origin protections apply to every route. An object ID requires a revision. Unknown selections return 422; stale revisions return 409 before planner invocation. Proposal request fingerprints include message/revision/selection, so the same key cannot silently target another object. Message-only older clients remain supported; they do not gain the displayed-revision check until updated. Legacy stored requests can still be replayed with their original message-only body.

Restore checks the current revision and retained source within one write transaction. Concurrent distinct requests for the same base revision allow only one successful mutation. Concurrent requests with the same key return the same response. If a successful response is lost, the pending browser action can resume with the original key/body, including after reload. Replaying a completed restore never reapplies it, even after later edits or pruning of the source snapshot. An unavailable source returns 404; conflicts and quotas leave project/history unchanged.

The default planner is deterministic and consumes no inference credits. If an operator later authorizes an external LLM, its typed output is also checked against the selected ID: changes or deletion of any other existing object are refused. This guard was tested with mock HTTP responses only. No real provider was called or billed during development.

## Existing-volume upgrade

Schema v2 is migrated automatically on the same Linux/local-volume architecture. API and worker serialize journal setup and transactional migration with an OS filesystem lock, released automatically if initialization exits. Both services must use the same application revision; no shared-network-filesystem or multi-host locking is supported.

Before updating, stop API and worker and back up the full volume. The migration preserves project IDs, revisions, jobs, artifacts and old proposals. It seeds only each project's current revision with reason `migration`: earlier names/scenes cannot be reconstructed reliably from render history. Existing render snapshots remain downloadable through their original jobs. New changes begin accumulating the retained history.

The previous API rejects schema v2. Roll back with a pre-upgrade volume backup or compatible code, not by altering the schema marker. The pinned v1 fixture is tested with four independent initializer processes; the unchanged pending job and legacy idempotent chat response are checked after upgrade. This is a same-host compatibility test, not a public deployment or device certification.
