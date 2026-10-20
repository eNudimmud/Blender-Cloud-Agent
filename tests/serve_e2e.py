"""Ephemeral developer-only server for Playwright. Never deploy this module."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import uvicorn

from app.config import Settings
from app.main import create_app
from app.store import Store

with tempfile.TemporaryDirectory(prefix='bca-e2e-') as temporary:
    settings = Settings(data_root=Path(temporary), api_token='e2e-test-key-only-never-production-123456789', secure_cookie=False)
    store = Store(settings)
    store.initialize()
    worker = None
    try:
        if os.environ.get('BLENDER_BIN'):
            worker = subprocess.Popen([sys.executable, '-m', 'worker.runner'], env={**os.environ, 'DATA_ROOT': temporary})
        uvicorn.run(create_app(settings), host='127.0.0.1', port=8765, log_level='warning')
    finally:
        if worker:
            worker.terminate()
            worker.wait(timeout=10)
