"""Validate real container isolation and the HTTP -> queue -> Blender -> artifact loop."""
import hashlib
import json
import os
import subprocess
import time
import uuid

import httpx


def compose(*args):
    return subprocess.check_output(['docker', 'compose', *args], text=True).strip()


for service in ('api', 'worker'):
    container = compose('ps', '-q', service)
    info = json.loads(subprocess.check_output(['docker', 'inspect', container], text=True))[0]
    assert info['Config']['User'] == '10001:10001'
    host = info['HostConfig']
    assert host['ReadonlyRootfs'] and 'ALL' in host['CapDrop']
    assert 'no-new-privileges:true' in host['SecurityOpt']
    assert host['Memory'] > 0 and host['NanoCpus'] > 0 and host['PidsLimit'] == 128
    assert not any(m['Source'] == '/var/run/docker.sock' for m in info['Mounts'])
    if service == 'worker':
        assert host['NetworkMode'] == 'none'
        assert not any(e.startswith(('API_TOKEN=', 'LLM_API_KEY=')) for e in info['Config']['Env'])
        compose('exec', '-T', service, 'python', '-c',
                "import os,socket; assert os.getuid()==10001; s=socket.socket(); s.settimeout(1); "
                "assert s.connect_ex(('1.1.1.1',443)) != 0")
    else:
        compose('exec', '-T', service, 'python', '-c', "import shutil; assert shutil.which('blender') is None")
    compose('exec', '-T', service, 'python', '-c',
            "import os; assert not os.access('/srv/app/app/main.py',os.W_OK)")

with httpx.Client(base_url='http://127.0.0.1:8000', headers={'Authorization': 'Bearer ' + os.environ['API_TOKEN']}) as client:
    p = client.post('/v1/projects', json={'name': 'Isolated container validation'},
                    headers={'Idempotency-Key': uuid.uuid4().hex}).raise_for_status().json()
    proposal = client.post(f"/v1/projects/{p['id']}/chat", json={'message': 'Ajoute une sphère bleue de taille 2'},
                           headers={'Idempotency-Key': uuid.uuid4().hex}).raise_for_status().json()
    job = client.post(f"/v1/projects/{p['id']}/proposals/{proposal['id']}/confirm").raise_for_status().json()
    deadline = time.monotonic() + 150
    while job['status'] in ('queued', 'running'):
        assert time.monotonic() < deadline, job
        time.sleep(1)
        job = client.get(f"/v1/jobs/{job['id']}").raise_for_status().json()
    assert job['status'] == 'succeeded', job
    for name, url in job['files'].items():
        response = client.get(url).raise_for_status()
        assert hashlib.sha256(response.content).hexdigest() == job['artifacts'][name]['sha256']
    print(json.dumps({'isolation': 'validated', 'blender': job['artifacts']['scene.glb']['blender_version'],
                      'project': p['id'], 'job': job['id'], 'artifacts': sorted(job['files'])}))
    compose('restart', 'api', 'worker')
    deadline = time.monotonic() + 30
    while True:
        try:
            persisted = client.get(f"/v1/projects/{p['id']}").raise_for_status().json()
            break
        except httpx.HTTPError:
            assert time.monotonic() < deadline
            time.sleep(1)
    assert persisted['revision'] == 2
    assert client.get(f"/v1/jobs/{job['id']}").json()['status'] == 'succeeded'
    assert client.get(job['files']['scene.glb']).status_code == 200
    print('Container restart persistence: validated')
