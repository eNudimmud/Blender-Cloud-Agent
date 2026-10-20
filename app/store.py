"""SQLite on one host/local volume. Transactions serialize claims and revisions."""
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

from fastapi import HTTPException

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, scene TEXT NOT NULL,
 revision INTEGER NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 revision INTEGER NOT NULL, scene TEXT NOT NULL, status TEXT NOT NULL,
 request_key TEXT NOT NULL, attempt TEXT, worker_id TEXT, lease_until REAL,
 error_code TEXT, manifest TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
 UNIQUE(project_id, request_key)
);
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status, created_at);
CREATE TABLE IF NOT EXISTS proposals (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 base_revision INTEGER NOT NULL, message TEXT NOT NULL, summary TEXT NOT NULL,
 scene TEXT, mode TEXT NOT NULL, request_key TEXT NOT NULL,
 job_id TEXT REFERENCES jobs(id), created_at REAL NOT NULL,
 UNIQUE(project_id, request_key)
);
CREATE TABLE IF NOT EXISTS workers (id TEXT PRIMARY KEY, seen_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS rates (key TEXT PRIMARY KEY, window INTEGER, count INTEGER);
CREATE TABLE IF NOT EXISTS project_keys (
 key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, project_id TEXT NOT NULL REFERENCES projects(id)
);
"""


def uid():
    return uuid.uuid4().hex


def require(row, detail="Resource not found"):
    if row is None:
        raise HTTPException(404, detail)
    return dict(row)


def project_dict(row):
    result = require(row, "Project not found")
    result["scene"] = json.loads(result["scene"])
    return result


def proposal_dict(row):
    result = require(row, "Proposal not found")
    result["scene"] = json.loads(result["scene"]) if result["scene"] else None
    result["supported"] = result["scene"] is not None
    result.pop("request_key", None)
    return result


def job_dict(row):
    result = require(row, "Job not found")
    manifest = json.loads(result["manifest"]) if result["manifest"] else {}
    return {
        key: result[key] for key in (
            "id", "project_id", "revision", "status", "error_code", "created_at", "updated_at"
        )
    } | {
        "scene": json.loads(result["scene"]),
        "files": {name: f"/v1/jobs/{result['id']}/files/{name}" for name in manifest},
        "artifacts": manifest,
    }


class Store:
    def __init__(self, settings):
        self.settings = settings
        self.root = settings.data_root.resolve()
        self.path = self.root / "agent.sqlite3"

    def initialize(self):
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "artifacts").mkdir(exist_ok=True)
        with self.connect() as con:
            version = con.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError("Unsupported database schema")
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(SCHEMA)
            con.execute("PRAGMA user_version=1")

    @contextmanager
    def connect(self, write=False):
        con = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                con.execute("BEGIN IMMEDIATE")
            yield con
            if write:
                con.commit()
        except BaseException:
            if write:
                con.rollback()
            raise
        finally:
            con.close()

    def rate_limit(self, key, limit, seconds=60):
        now = int(time.time())
        window = now // seconds
        with self.connect(write=True) as con:
            con.execute("DELETE FROM rates WHERE window < ?", (window - 2,))
            row = con.execute("SELECT * FROM rates WHERE key=?", (key,)).fetchone()
            count = row["count"] if row and row["window"] == window else 0
            if count >= limit:
                raise HTTPException(429, "Trop de requêtes. Réessaie dans une minute.",
                                    headers={"Retry-After": str(seconds - now % seconds)})
            con.execute("INSERT OR REPLACE INTO rates VALUES (?,?,?)", (key, window, count + 1))

    def get_project(self, project_id):
        with self.connect() as con:
            return project_dict(con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())

    def get_job(self, job_id):
        with self.connect() as con:
            return require(con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def enqueue(self, con, project, key):
        existing = con.execute("SELECT * FROM jobs WHERE project_id=? AND request_key=?",
                               (project["id"], key)).fetchone()
        if existing:
            if existing["revision"] != project["revision"]:
                raise HTTPException(409, "Cette clé a déjà servi pour une autre version.")
            return dict(existing)
        pending = con.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
        total = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        if pending >= self.settings.max_pending_jobs or total >= self.settings.max_jobs:
            raise HTTPException(429, "Limite de rendus atteinte.")
        used = con.execute("SELECT manifest FROM jobs WHERE manifest IS NOT NULL").fetchall()
        size = sum(a["bytes"] for row in used for a in json.loads(row[0]).values())
        if size >= self.settings.max_storage_bytes:
            raise HTTPException(507, "Stockage plein.")
        job_id, now = uid(), time.time()
        scene = project["scene"]
        if not isinstance(scene, str):
            scene = json.dumps(scene)
        con.execute("""INSERT INTO jobs
            (id,project_id,revision,scene,status,request_key,created_at,updated_at)
            VALUES (?,?,?,?,'queued',?,?,?)""",
                    (job_id, project["id"], project["revision"], scene, key, now, now))
        return dict(con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def heartbeat(self, worker_id):
        with self.connect(write=True) as con:
            con.execute("DELETE FROM workers WHERE seen_at < ?", (time.time() - 3600,))
            con.execute("INSERT OR REPLACE INTO workers VALUES (?,?)", (worker_id, time.time()))

    def claim(self, worker_id):
        now = time.time()
        with self.connect(write=True) as con:
            # No automatic replay: user can explicitly retry a failed render.
            con.execute("""UPDATE jobs SET status='failed',error_code='worker_lost',updated_at=?
                WHERE status='running' AND lease_until < ?""", (now, now))
            row = con.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not row:
                return None
            attempt = uid()
            con.execute("""UPDATE jobs SET status='running',attempt=?,worker_id=?,lease_until=?,updated_at=?
                WHERE id=? AND status='queued'""",
                        (attempt, worker_id, now + self.settings.job_timeout + 30, now, row["id"]))
            return dict(con.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())

    def finish(self, job, status, manifest=None, error=None):
        with self.connect(write=True) as con:
            return con.execute("""UPDATE jobs SET status=?,manifest=?,error_code=?,updated_at=?
                WHERE id=? AND status='running' AND attempt=? AND lease_until >= ?""",
                               (status, json.dumps(manifest) if manifest else None, error,
                                time.time(), job["id"], job["attempt"], time.time())).rowcount == 1
