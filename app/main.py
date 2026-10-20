import os
import subprocess
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

app = FastAPI(title="Blender Cloud Agent", version="0.1.0")
ARTIFACT_ROOT = Path(os.environ.get("ARTIFACT_ROOT", "/tmp/blender-agent-artifacts")).resolve()
BLENDER_BIN = os.environ.get("BLENDER_BIN", "blender")
WORKER_SCRIPT = Path(__file__).resolve().parents[1] / "worker" / "generate.py"
STATIC_DIR = Path(__file__).resolve().parent / "static"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/", include_in_schema=False)
def mobile_home():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")

class SceneRequest(BaseModel):
    shape: Literal["cube", "sphere", "cylinder"] = "cube"
    size: float = Field(default=2, gt=0, le=20)
    name: str = Field(default="My First Scene", min_length=1, max_length=80)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/v1/scenes", status_code=201)
def create_scene(request: SceneRequest):
    job_id = uuid.uuid4().hex
    output_dir = ARTIFACT_ROOT / job_id
    output_dir.mkdir(parents=True, exist_ok=False)
    command = [BLENDER_BIN, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(WORKER_SCRIPT), "--", request.shape, str(request.size), str(output_dir)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(503, detail=f"Blender worker unavailable: {type(exc).__name__}") from exc
    if result.returncode != 0:
        raise HTTPException(500, detail="Blender worker failed; inspect server logs")
    expected = ["scene.blend", "scene.glb", "preview.png"]
    if not all((output_dir / filename).is_file() for filename in expected):
        raise HTTPException(500, detail="Worker did not produce all expected artifacts")
    return {"id": job_id, "name": request.name, "files": {f: f"/v1/scenes/{job_id}/files/{f}" for f in expected}}

@app.get("/v1/scenes/{job_id}/files/{filename}")
def get_artifact(job_id: str, filename: Literal["scene.blend", "scene.glb", "preview.png"]):
    if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
        raise HTTPException(404, "Scene not found")
    path = ARTIFACT_ROOT / job_id / filename
    if not path.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(path)
