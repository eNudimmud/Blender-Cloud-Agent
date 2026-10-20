"""Offline queue consumer. Run only in the isolated worker service in production."""
import argparse
import hashlib
import json
import os
import shutil
import signal
import struct
import subprocess
import tempfile
import time
from pathlib import Path

from app.config import Settings
from app.models import SceneSpec
from app.store import Store, uid

SCRIPT = Path(__file__).with_name("generate.py").resolve()
MAX_FILE_BYTES = 64 * 1024**2
MAX_LOG_BYTES = 4 * 1024**2


class JobFailure(Exception):
    pass


def artifact_manifest(directory):
    manifest = {}
    expected = {"scene.blend": b"BLENDER", "scene.glb": b"glTF", "preview.png": b"\x89PNG\r\n\x1a\n"}
    metadata = json.loads((directory / "metadata.json").read_text())
    for name, magic in expected.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or not 16 <= path.stat().st_size <= MAX_FILE_BYTES:
            raise JobFailure("invalid_artifact")
        with path.open("rb") as source:
            header = source.read(24)
        if not header.startswith(magic):
            raise JobFailure("invalid_artifact")
        if name == "scene.glb":
            _, version, length = struct.unpack("<4sII", header[:12])
            if version != 2 or length != path.stat().st_size:
                raise JobFailure("invalid_artifact")
        if name == "preview.png" and struct.unpack(">II", header[16:24]) != (640, 480):
            raise JobFailure("invalid_artifact")
        manifest[name] = {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                          "blender_version": metadata["blender_version"]}
    return manifest


def stop_process(proc):
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    proc.wait()


def run_one(store, worker_id):
    store.heartbeat(worker_id)
    job = store.claim(worker_id)
    if job is None:
        return None
    directory = store.root / "artifacts" / job["id"] / job["attempt"]
    proc = None
    try:
        scene = SceneSpec.model_validate_json(job["scene"])
        if shutil.disk_usage(store.root).free < 256 * 1024**2:
            raise JobFailure("disk_full")
        directory.mkdir(parents=True, exist_ok=False)
        with tempfile.TemporaryDirectory(prefix="bca-job-") as temporary:
            work = Path(temporary)
            spec_file = work / "scene.json"
            spec_file.write_text(scene.model_dump_json())
            # No API or LLM keys, proxy variables, or arbitrary script content reach Blender.
            env = {k: os.environ[k] for k in ("PATH", "LD_LIBRARY_PATH", "BLENDER_SYSTEM_SCRIPTS", "BLENDER_SYSTEM_DATAFILES") if k in os.environ}
            env.update({"HOME": temporary, "TMPDIR": temporary, "LANG": "C.UTF-8", "OMP_NUM_THREADS": "2"})
            command = [store.settings.blender_bin, "--background", "--factory-startup", "--disable-autoexec",
                       "--threads", "2", "--python-exit-code", "1", "--python", str(SCRIPT),
                       "--", str(spec_file), str(directory)]
            with tempfile.TemporaryFile() as log:
                proc = subprocess.Popen(command, cwd=temporary, env=env, stdout=log, stderr=subprocess.STDOUT,
                                        start_new_session=True, stdin=subprocess.DEVNULL)
                started, heartbeat = time.monotonic(), 0
                while proc.poll() is None:
                    now = time.monotonic()
                    if now - started > store.settings.job_timeout:
                        raise JobFailure("timeout")
                    current = store.get_job(job["id"])
                    if current["status"] != "running" or current["attempt"] != job["attempt"]:
                        raise JobFailure("cancelled")
                    if log.tell() > MAX_LOG_BYTES:
                        raise JobFailure("log_limit")
                    if now - heartbeat >= 3:
                        store.heartbeat(worker_id)
                        heartbeat = now
                    time.sleep(0.2)
                if proc.returncode:
                    raise JobFailure("blender_failed")
        manifest = artifact_manifest(directory)
        if not store.finish(job, "succeeded", manifest=manifest):
            raise JobFailure("lease_lost")
        return job["id"]
    except Exception as exc:
        if proc is not None:
            stop_process(proc)
        error = str(exc) if isinstance(exc, JobFailure) else "worker_error"
        store.finish(job, "failed", error=error)
        shutil.rmtree(directory, ignore_errors=True)
        print(json.dumps({"job": job["id"], "error": error}), flush=True)
        return job["id"]
    finally:
        store.heartbeat(worker_id)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Consume at most one job, for smoke tests")
    args = parser.parse_args()
    settings = Settings.from_env()
    if not 5 <= settings.job_timeout <= 300:
        raise ValueError("JOB_TIMEOUT must be between 5 and 300 seconds")
    store = Store(settings)
    store.initialize()
    worker_id = uid()
    while True:
        result = run_one(store, worker_id)
        if args.once:
            break
        if result is None:
            time.sleep(1)


if __name__ == "__main__":
    main()
