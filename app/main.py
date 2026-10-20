import hashlib
import hmac
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.agent import guided_plan, llm_plan
from app.config import Settings
from app.models import (
    ChatRequest,
    JobView,
    Login,
    PortableProject,
    ProjectCreate,
    ProjectEdit,
    ProjectView,
    ProposalView,
    RenderRequest,
    SceneSpec,
)
from app.security import COOKIE, BodyLimitMiddleware, authenticated, client_address, session_cookie
from app.store import Store, job_dict, project_dict, proposal_dict, require, uid

STATIC_DIR = Path(__file__).resolve().parent / "static"
RequestKey = Annotated[str, Header(alias="Idempotency-Key", pattern=r"^[A-Za-z0-9_-]{8,100}$")]


def create_app(settings=None):
    settings = settings or Settings.from_env()
    store = Store(settings)

    @asynccontextmanager
    async def lifespan(app):
        settings.validate_api()
        store.initialize()
        yield

    app = FastAPI(title="Blender Cloud Agent", version="0.2.0", lifespan=lifespan)
    app.state.store = store
    app.state.settings = settings
    app.add_middleware(BodyLimitMiddleware)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"detail": [{k: e[k] for k in ("type", "loc", "msg")} for e in exc.errors()]}, 422)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if path.startswith("/v1/"):
            is_session = path == "/v1/auth/session"
            authorized = authenticated(request, settings.api_token) if settings.api_token else False
            if not is_session and not authorized:
                return JSONResponse({"detail": "Connexion requise."}, 401)
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                origin = request.headers.get("origin")
                expected = settings.public_origin or str(request.base_url).rstrip("/")
                if origin and origin != expected:
                    return JSONResponse({"detail": "Origin refused"}, 403)
                if not request.headers.get("authorization", "").startswith("Bearer ") and request.headers.get("x-csrf-token") != "1":
                    return JSONResponse({"detail": "CSRF header required"}, 403)
            if not is_session:
                try:
                    await run_in_threadpool(store.rate_limit, "read" if request.method == "GET" else "write",
                                            360 if request.method == "GET" else 60)
                except HTTPException as exc:
                    return JSONResponse({"detail": exc.detail}, exc.status_code, headers=exc.headers)
        response = await call_next(request)
        return response

    @app.middleware("http")
    async def response_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.update({
            "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        })
        if request.url.path.startswith("/v1/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def mobile_home():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/v1/auth/session")
    def session(request: Request):
        return {"authenticated": authenticated(request, settings.api_token)}

    @app.post("/v1/auth/session")
    def login(request: Request, body: Login, response: Response):
        store.rate_limit("login:" + client_address(request, settings.proxy_key), 5)
        if not hmac.compare_digest(body.token.encode(), settings.api_token.encode()):
            raise HTTPException(401, "Clé incorrecte.")
        response.set_cookie(COOKIE, session_cookie(settings.api_token), max_age=43200,
                            httponly=True, secure=settings.secure_cookie, samesite="strict", path="/")
        return {"authenticated": True}

    @app.delete("/v1/auth/session", status_code=204)
    def logout(response: Response):
        response.delete_cookie(COOKIE, path="/")

    @app.get("/v1/capabilities")
    def capabilities():
        with store.connect() as con:
            count = con.execute("SELECT COUNT(*) FROM workers WHERE seen_at > ?", (time.time() - 15,)).fetchone()[0]
        return {"schema_version": 1, "agent_mode": settings.agent_mode,
                "paid_ai_enabled": settings.allow_paid_ai, "workers_online": count,
                "shapes": ["cube", "sphere", "cylinder"], "max_objects": 24,
                "workspace": "single-owner", "mcp_enabled": False}

    @app.get("/v1/schema/scene")
    def scene_schema():
        return SceneSpec.model_json_schema()

    @app.get("/v1/projects", response_model=list[ProjectView])
    def list_projects():
        with store.connect() as con:
            return [project_dict(r) for r in con.execute("SELECT * FROM projects ORDER BY updated_at DESC LIMIT 100")]

    @app.post("/v1/projects", status_code=201, response_model=ProjectView)
    def create_project(body: ProjectCreate, key: RequestKey):
        fingerprint = hashlib.sha256(json.dumps(body.model_dump(mode="json", exclude_unset=True), sort_keys=True).encode()).hexdigest()
        with store.connect(write=True) as con:
            old = con.execute("SELECT * FROM project_keys WHERE key=?", (key,)).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise HTTPException(409, "Clé déjà utilisée pour un autre projet.")
                return project_dict(con.execute("SELECT * FROM projects WHERE id=?", (old["project_id"],)).fetchone())
            if con.execute("SELECT COUNT(*) FROM projects").fetchone()[0] >= settings.max_projects:
                raise HTTPException(429, "Limite de projets atteinte.")
            project_id, now = uid(), time.time()
            con.execute("INSERT INTO projects VALUES (?,?,?,1,?,?)",
                        (project_id, body.name, body.scene.model_dump_json(), now, now))
            con.execute("INSERT INTO project_keys VALUES (?,?,?)", (key, fingerprint, project_id))
            return project_dict(con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())

    @app.get("/v1/projects/{project_id}", response_model=ProjectView)
    def get_project(project_id: str):
        return store.get_project(project_id)

    @app.post("/v1/projects/import", status_code=201, response_model=ProjectView)
    def import_project(body: PortableProject, key: RequestKey):
        # Always create a separate project. Source metadata never grants overwrite authority.
        return create_project(body.project, key)

    @app.get("/v1/projects/{project_id}/export", response_model=PortableProject)
    def export_project(project_id: str):
        project = store.get_project(project_id)
        portable = PortableProject(
            project=ProjectCreate(name=project["name"], scene=project["scene"]),
            source={"project_id": project_id, "revision": project["revision"]},
        )
        return JSONResponse(portable.model_dump(mode="json"), headers={
            "Content-Disposition": f'attachment; filename="project-{project_id}.bca.json"',
        })

    @app.put("/v1/projects/{project_id}", response_model=ProjectView)
    def update_project(project_id: str, body: ProjectEdit):
        with store.connect(write=True) as con:
            project = require(con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())
            if project["revision"] != body.revision:
                raise HTTPException(409, "Le projet a changé. Recharge sa dernière version.")
            con.execute("UPDATE projects SET name=?,scene=?,revision=revision+1,updated_at=? WHERE id=?",
                        (body.name, body.scene.model_dump_json(), time.time(), project_id))
            return project_dict(con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())

    @app.get("/v1/projects/{project_id}/jobs", response_model=list[JobView])
    def list_jobs(project_id: str):
        store.get_project(project_id)
        with store.connect() as con:
            return [job_dict(r) for r in con.execute("SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC LIMIT 50", (project_id,))]

    @app.post("/v1/projects/{project_id}/jobs", status_code=202, response_model=JobView)
    def render(project_id: str, body: RenderRequest, key: RequestKey):
        with store.connect(write=True) as con:
            project = require(con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())
            old = con.execute("SELECT * FROM jobs WHERE project_id=? AND request_key=?", (project_id, key)).fetchone()
            if old and old["revision"] == body.revision:
                return job_dict(old)
            if project["revision"] != body.revision:
                raise HTTPException(409, "Cette version du projet n’est plus à jour.")
            return job_dict(store.enqueue(con, project, key))

    @app.get("/v1/jobs/{job_id}", response_model=JobView)
    def get_job(job_id: str):
        return job_dict(store.get_job(job_id))

    @app.post("/v1/jobs/{job_id}/cancel", response_model=JobView)
    def cancel_job(job_id: str):
        with store.connect(write=True) as con:
            require(con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
            con.execute("UPDATE jobs SET status='cancelled',updated_at=? WHERE id=? AND status IN ('queued','running')", (time.time(), job_id))
            return job_dict(con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    @app.get("/v1/jobs/{job_id}/files/{filename}")
    def get_artifact(job_id: str, filename: Literal["scene.blend", "scene.glb", "preview.png"]):
        job = store.get_job(job_id)
        files = json.loads(job["manifest"]) if job["manifest"] else {}
        if job["status"] != "succeeded" or filename not in files:
            raise HTTPException(404, "Artifact not available")
        directory = (store.root / "artifacts" / job["id"] / job["attempt"]).resolve()
        path = directory / filename
        if (path.is_symlink() or not path.is_file() or path.resolve().parent != directory
                or not directory.is_relative_to(store.root / "artifacts")):
            raise HTTPException(404, "Artifact not available")
        media = {"scene.glb": "model/gltf-binary", "preview.png": "image/png", "scene.blend": "application/octet-stream"}
        return FileResponse(path, media_type=media[filename], filename=filename, content_disposition_type="inline" if filename != "scene.blend" else "attachment")

    @app.get("/v1/projects/{project_id}/chat", response_model=list[ProposalView])
    def chat_history(project_id: str):
        store.get_project(project_id)
        with store.connect() as con:
            rows = con.execute("SELECT * FROM proposals WHERE project_id=? ORDER BY created_at DESC LIMIT 50", (project_id,)).fetchall()
            return [proposal_dict(r) for r in reversed(rows)]

    @app.post("/v1/projects/{project_id}/chat", status_code=201, response_model=ProposalView)
    def chat(project_id: str, body: ChatRequest, key: RequestKey):
        project = store.get_project(project_id)
        with store.connect() as con:
            old = con.execute("SELECT * FROM proposals WHERE project_id=? AND request_key=?", (project_id, key)).fetchone()
            if old:
                if old["message"] != body.message:
                    raise HTTPException(409, "Clé déjà utilisée pour un autre message.")
                return proposal_dict(old)
        store.rate_limit("planner", 20)
        try:
            scene = SceneSpec.model_validate(project["scene"])
            if settings.agent_mode == "llm":
                history = [{"request": p["message"], "summary": p["summary"]} for p in chat_history(project_id)[-6:]]
                plan = llm_plan(settings, scene, body.message, history)
            else:
                plan = guided_plan(scene, body.message)
        except ValidationError:
            raise HTTPException(422, "La proposition dépasse les limites de la scène. Taille 0,1–20 ; positions −50–50 ; 24 objets maximum.") from None
        except (ValueError, httpx.HTTPError, KeyError, TypeError):
            raise HTTPException(503, "Planificateur IA indisponible ou désactivé. Aucun rendu lancé.") from None
        with store.connect(write=True) as con:
            old = con.execute("SELECT * FROM proposals WHERE project_id=? AND request_key=?", (project_id, key)).fetchone()
            if old:
                if old["message"] != body.message:
                    raise HTTPException(409, "Clé déjà utilisée.")
                return proposal_dict(old)
            current = require(con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())
            if current["revision"] != project["revision"]:
                raise HTTPException(409, "Le projet a changé pendant la préparation. Réessaie.")
            if con.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] >= 2000:
                raise HTTPException(429, "Limite de conversation atteinte.")
            proposal_id = uid()
            con.execute("""INSERT INTO proposals
                (id,project_id,base_revision,message,summary,scene,mode,request_key,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""", (proposal_id, project_id, project["revision"], body.message,
                        plan.summary, plan.scene.model_dump_json() if plan.scene else None, settings.agent_mode, key, time.time()))
            return proposal_dict(con.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone())

    @app.post("/v1/projects/{project_id}/proposals/{proposal_id}/confirm", status_code=202, response_model=JobView)
    def confirm(project_id: str, proposal_id: str):
        with store.connect(write=True) as con:
            proposal = require(con.execute("SELECT * FROM proposals WHERE id=? AND project_id=?", (proposal_id, project_id)).fetchone())
            if proposal["job_id"]:
                return job_dict(con.execute("SELECT * FROM jobs WHERE id=?", (proposal["job_id"],)).fetchone())
            if not proposal["scene"]:
                raise HTTPException(422, "Aucune modification à confirmer.")
            project = require(con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())
            if project["revision"] != proposal["base_revision"]:
                raise HTTPException(409, "Proposition périmée. Prépare une nouvelle demande.")
            SceneSpec.model_validate_json(proposal["scene"])
            con.execute("UPDATE projects SET scene=?,revision=revision+1,updated_at=? WHERE id=?", (proposal["scene"], time.time(), project_id))
            updated = dict(con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())
            job = store.enqueue(con, updated, "proposal_" + proposal_id)
            con.execute("UPDATE proposals SET job_id=? WHERE id=?", (job["id"], proposal_id))
            return job_dict(job)

    return app


app = create_app()
