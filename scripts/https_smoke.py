"""CI-only HTTPS check with a verified local CA, not a public certificate claim."""
import json
import os
import ssl
import subprocess
import time
import uuid

import httpx


def compose(*args):
    return subprocess.check_output(['docker', 'compose', *args], text=True).strip()


def container_info(service):
    return json.loads(subprocess.check_output(['docker', 'inspect', compose('ps', '-q', service)], text=True))[0]


api = container_info('api')
proxy = container_info('proxy')
worker = container_info('worker')
assert not api['HostConfig']['PortBindings'], 'The API must not expose a host port in HTTPS mode'
assert proxy['Config']['User'] == '10001:10001'
assert proxy['HostConfig']['ReadonlyRootfs'] and 'ALL' in proxy['HostConfig']['CapDrop']
assert 'no-new-privileges:true' in proxy['HostConfig']['SecurityOpt']
assert compose('exec', '-T', 'proxy', 'getcap', '/usr/bin/caddy') == ''
assert worker['HostConfig']['NetworkMode'] == 'none'
assert not any(value.startswith(('API_TOKEN=', 'LLM_API_KEY=', 'PROXY_SHARED_KEY=')) for value in worker['Config']['Env'])

deadline = time.monotonic() + 30
while True:
    try:
        certificate = compose('exec', '-T', 'proxy', 'cat', '/data/caddy/pki/authorities/local/root.crt')
        break
    except subprocess.CalledProcessError:
        assert time.monotonic() < deadline
        time.sleep(1)
context = ssl.create_default_context(cadata=certificate)
with httpx.Client(base_url='https://localhost', verify=context, follow_redirects=False, trust_env=False) as client:
    while True:
        try:
            assert client.get('/health').raise_for_status().json()['status'] == 'ok'
            break
        except httpx.HTTPError:
            assert time.monotonic() < deadline
            time.sleep(1)
    redirect = client.get('http://localhost/health')
    assert redirect.status_code in (301, 302, 307, 308)
    assert redirect.headers['location'] == 'https://localhost/health', redirect.headers['location']
    response = client.get('/v1/projects')
    assert response.status_code == 401 and response.headers['cache-control'] == 'no-store'
    assert response.headers['strict-transport-security'] == 'max-age=31536000'
    assert 'alt-svc' not in response.headers  # This overlay publishes TCP, not HTTP/3 UDP.
    response = client.post('/v1/auth/session', headers={'Origin': 'https://localhost', 'X-CSRF-Token': '1',
                           'X-BCA-Client-IP': '203.0.113.9', 'X-BCA-Proxy-Key': 'spoofed'},
                           json={'token': os.environ['API_TOKEN']})
    response.raise_for_status()
    cookie = response.headers['set-cookie']
    assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=strict' in cookie
    assert client.get('/v1/projects').status_code == 200
    assert client.post('/v1/projects', headers={'Origin': 'https://evil.example', 'X-CSRF-Token': '1'},
                       json={},).status_code == 403
    assert client.post('/v1/projects', json={}).status_code == 403
    client.headers.update({'Origin': 'https://localhost', 'X-CSRF-Token': '1'})
    created = client.post('/v1/projects', headers={'Idempotency-Key': uuid.uuid4().hex},
                          json={'name': 'HTTPS project'}).raise_for_status().json()
    portable = client.get(f"/v1/projects/{created['id']}/export").raise_for_status()
    assert 'attachment' in portable.headers['content-disposition']
    imported = client.post('/v1/projects/import', headers={'Idempotency-Key': uuid.uuid4().hex},
                           json=portable.json()).raise_for_status().json()
    assert imported['id'] != created['id'] and imported['scene'] == created['scene']
    assert client.delete('/v1/auth/session').status_code == 204
    assert client.get('/v1/projects').status_code == 401
    client.cookies.clear()
    client.headers['Authorization'] = 'Bearer ' + os.environ['API_TOKEN']
    assert client.get(f"/v1/projects/{imported['id']}").status_code == 200
    assert client.get('/v1/capabilities').json()['paid_ai_enabled'] is False

keys = json.loads(compose('exec', '-T', 'api', 'python', '-c',
    "import sqlite3,json; c=sqlite3.connect('/data/agent.sqlite3'); "
    "print(json.dumps([r[0] for r in c.execute(\"SELECT key FROM rates WHERE key LIKE 'login:%'\")]))"))
assert keys and 'login:203.0.113.9' not in keys
print(json.dumps({'https': 'verified-with-test-CA', 'secure_cookie': True, 'csrf': 'validated',
                  'api_host_port': 'none', 'spoofed_client_ip': 'refused', 'portable_projects': 'round-trip-validated'}))
