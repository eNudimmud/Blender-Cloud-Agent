-- Schema from main 0a322733d09a9a2838416300bbf13a017b939f81. Keep as a migration fixture.

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

PRAGMA user_version=1;
