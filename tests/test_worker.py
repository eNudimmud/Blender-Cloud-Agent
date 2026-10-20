import json
import os
import struct
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from app.models import SceneObject
from app.store import Store
from tests.conftest import key
from worker.runner import artifact_manifest, run_one


def enqueue(client, project):
    response = client.post(f"/v1/projects/{project['id']}/jobs", json={'revision': project['revision']}, headers=key())
    assert response.status_code == 202
    return response.json()


def binary(tmp_path, content):
    path = tmp_path / 'fake-blender'
    path.write_text(f'#!{sys.executable}\n' + content)
    path.chmod(0o700)
    return str(path)


@pytest.fixture
def successful_binary(tmp_path):
    return binary(tmp_path, '''
import json, os, struct, sys
from pathlib import Path
out = Path(sys.argv[-1])
assert 'API_TOKEN' not in os.environ
assert 'LLM_API_KEY' not in os.environ
(out / 'scene.blend').write_bytes(b'BLENDER' + b'_' * 32)
(out / 'scene.glb').write_bytes(struct.pack('<4sII', b'glTF', 2, 16) + b'____')
(out / 'preview.png').write_bytes(b'\\x89PNG\\r\\n\\x1a\\n' + b'_'*8 + struct.pack('>II', 640, 480))
(out / 'metadata.json').write_text(json.dumps({'blender_version':'fake-for-lifecycle-tests'}))
''')


def test_worker_claim_is_atomic_and_fenced(client, project, app):
    queued = enqueue(client, project)
    store = app.state.store
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(store.claim, ['worker-a', 'worker-b', 'worker-c', 'worker-d']))
    assert sum(job is not None for job in claims) == 1
    job = next(job for job in claims if job)
    assert job['id'] == queued['id']
    obsolete = dict(job, attempt='0' * 32)
    assert store.finish(obsolete, 'succeeded', manifest={}) is False
    assert store.get_job(job['id'])['status'] == 'running'


def test_expired_lease_is_failed_without_replay(client, project, app):
    queued = enqueue(client, project)
    store = app.state.store
    job = store.claim('lost-worker')
    with store.connect(write=True) as con:
        con.execute('UPDATE jobs SET lease_until=? WHERE id=?', (time.time() - 1, job['id']))
    assert store.claim('new-worker') is None
    assert store.get_job(queued['id'])['error_code'] == 'worker_lost'
    assert not store.finish(job, 'succeeded', manifest={})


def test_worker_success_and_artifact_auth(client, project, settings, successful_binary):
    job = enqueue(client, project)
    store = Store(replace(settings, blender_bin=successful_binary))
    run_one(store, 'offline-worker')
    result = client.get(f"/v1/jobs/{job['id']}").json()
    assert result['status'] == 'succeeded'
    assert set(result['files']) == {'scene.blend', 'scene.glb', 'preview.png'}
    for name, path in result['files'].items():
        response = client.get(path)
        assert response.status_code == 200
        assert len(response.content) == result['artifacts'][name]['bytes']
        assert response.headers['cache-control'] == 'no-store'
    client.headers.pop('Authorization')
    assert client.get(result['files']['scene.glb']).status_code == 401


def test_symlink_artifact_refused(client, project, settings, successful_binary, tmp_path):
    job = enqueue(client, project)
    store = Store(replace(settings, blender_bin=successful_binary))
    run_one(store, 'worker')
    saved = store.get_job(job['id'])
    artifact = settings.data_root / 'artifacts' / job['id'] / saved['attempt'] / 'scene.glb'
    target = tmp_path / 'secret'
    target.write_text('private')
    artifact.unlink()
    artifact.symlink_to(target)
    assert client.get(f"/v1/jobs/{job['id']}/files/scene.glb").status_code == 404


def test_cancelled_job_is_not_claimed(client, project, app):
    job = enqueue(client, project)
    client.post(f"/v1/jobs/{job['id']}/cancel")
    assert app.state.store.claim('worker') is None


def test_running_cancellation_kills_process(client, project, settings, tmp_path):
    job = enqueue(client, project)
    executable = binary(tmp_path, 'import time\ntime.sleep(30)\n')
    store = Store(replace(settings, blender_bin=executable))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run_one, store, 'worker')
        deadline = time.monotonic() + 5
        while store.get_job(job['id'])['status'] != 'running':
            assert time.monotonic() < deadline
            time.sleep(.01)
        client.post(f"/v1/jobs/{job['id']}/cancel")
        future.result(timeout=5)
    assert store.get_job(job['id'])['status'] == 'cancelled'
    assert list((settings.data_root / 'artifacts' / job['id']).glob('*')) == []


def test_timeout_cleans_partial_outputs(client, project, settings, tmp_path):
    job = enqueue(client, project)
    executable = binary(tmp_path, 'import time\ntime.sleep(30)\n')
    store = Store(replace(settings, blender_bin=executable, job_timeout=.25))
    run_one(store, 'worker')
    assert store.get_job(job['id'])['error_code'] == 'timeout'
    assert not client.get(f"/v1/jobs/{job['id']}").json()['files']
    assert list((settings.data_root / 'artifacts' / job['id']).glob('*')) == []


def test_bad_artifacts_fail_closed(client, project, settings, tmp_path):
    job = enqueue(client, project)
    executable = binary(tmp_path, 'from pathlib import Path\nimport sys\nPath(sys.argv[-1], "scene.glb").write_text("partial")\n')
    store = Store(replace(settings, blender_bin=executable))
    run_one(store, 'worker')
    assert store.get_job(job['id'])['status'] == 'failed'
    assert client.get(f"/v1/jobs/{job['id']}/files/scene.glb").status_code == 404


def glb_document(path):
    data = Path(path).read_bytes()
    length, kind = struct.unpack('<I4s', data[12:20])
    assert kind == b'JSON'
    return json.loads(data[20:20 + length])


@pytest.mark.blender
@pytest.mark.parametrize('shapes', [['cube'], ['sphere'], ['cylinder'], ['cube', 'sphere', 'cylinder'], []])
def test_real_blender_headless(client, settings, shapes):
    executable = os.environ.get('BLENDER_BIN')
    if not executable:
        pytest.skip('Set BLENDER_BIN for real Blender integration tests')
    objects = [SceneObject(shape=shape, name=shape, position=(index * 3, 0, 0)).model_dump(mode='json')
               for index, shape in enumerate(shapes)]
    project = client.post('/v1/projects', json={'name': 'Real Blender', 'scene': {'objects': objects}}, headers=key()).json()
    job = enqueue(client, project)
    store = Store(replace(settings, blender_bin=executable))
    run_one(store, 'real-worker')
    result = client.get(f"/v1/jobs/{job['id']}").json()
    assert result['status'] == 'succeeded', result
    saved = store.get_job(job['id'])
    directory = settings.data_root / 'artifacts' / job['id'] / saved['attempt']
    manifest = artifact_manifest(directory)
    assert manifest['scene.blend']['blender_version'] == '4.5.3 LTS'
    gltf = glb_document(directory / 'scene.glb')
    assert len(gltf.get('meshes', [])) == len(shapes)
    nodes = [node for node in gltf.get('nodes', []) if 'mesh' in node]
    assert {node['extras']['bca_object_id'] for node in nodes} == {o['id'] for o in objects}
    for name, path in result['files'].items():
        assert client.get(path).status_code == 200
