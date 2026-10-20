from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.security import COOKIE
from tests.conftest import TOKEN, key


def test_health_and_mobile_shell(client):
    assert client.get('/health').json() == {'status': 'ok'}
    assert 'BLENDER CLOUD' in client.get('/').text
    assert client.get('/manifest.webmanifest').json()['display'] == 'standalone'
    assert client.get('/v1/capabilities').json()['paid_ai_enabled'] is False
    assert client.get('/v1/capabilities').json()['workers_online'] == 0
    assert 'cdn' not in client.get('/static/app.js').text


def test_requires_access_key(app):
    with TestClient(app) as c:
        for path in ['/v1/projects', '/v1/jobs/anything', '/v1/schema/scene', '/v1/jobs/x/files/scene.glb']:
            assert c.get(path).status_code == 401
        assert c.post('/v1/projects', json={}).status_code == 401


def test_cookie_login_csrf_and_logout(app):
    with TestClient(app) as c:
        assert not c.get('/v1/auth/session').json()['authenticated']
        assert c.post('/v1/auth/session', json={'token': TOKEN}).status_code == 403
        c.headers['X-CSRF-Token'] = '1'
        r = c.post('/v1/auth/session', json={'token': TOKEN})
        assert r.status_code == 200
        assert 'HttpOnly' in r.headers['set-cookie'] and 'SameSite=strict' in r.headers['set-cookie']
        assert TOKEN not in c.cookies.get(COOKIE)
        assert c.get('/v1/projects').status_code == 200
        assert c.post('/v1/projects', json={}, headers=key() | {'Origin': 'https://evil.example'}).status_code == 403
        assert c.delete('/v1/auth/session').status_code == 204
        assert c.get('/v1/projects').status_code == 401


def test_cookie_tampering(app):
    with TestClient(app) as c:
        c.cookies.set(COOKIE, '0.nonce.invalid')
        assert c.get('/v1/projects').status_code == 401


def test_secure_cookie_and_startup_key(settings):
    with TestClient(create_app(replace(settings, secure_cookie=True))) as c:
        r = c.post('/v1/auth/session', json={'token': TOKEN}, headers={'X-CSRF-Token': '1'})
        assert 'Secure' in r.headers['set-cookie']
    with pytest.raises(ValueError, match='API_TOKEN'):
        with TestClient(create_app(replace(settings, api_token=''))):
            pass


def test_login_limits_and_redacts_validation(app):
    with TestClient(app) as c:
        c.headers['X-CSRF-Token'] = '1'
        secret = 'sensitive-password' * 30
        r = c.post('/v1/auth/session', json={'token': secret})
        assert r.status_code == 422 and secret not in r.text
        assert c.post('/v1/auth/session', json={'token': 'é' * 32}).status_code == 401
        for _ in range(4):
            assert c.post('/v1/auth/session', json={'token': 'bad'}).status_code == 401
        assert c.post('/v1/auth/session', json={'token': TOKEN}).status_code == 429


def test_body_limit_including_chunked(client):
    response = client.post('/v1/projects', content=(b'x' * 20000 for _ in range(2)), headers=key())
    assert response.status_code == 413


def test_create_idempotency_with_generated_object_ids(client):
    body = {'scene': {'objects': [{'shape': 'cube'}]}}
    headers = key()
    first = client.post('/v1/projects', json=body, headers=headers)
    second = client.post('/v1/projects', json=body, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()['id'] == second.json()['id']
    assert first.json()['scene'] == second.json()['scene']
    assert client.post('/v1/projects', json={'name': 'other'}, headers=headers).status_code == 409


def test_project_optimistic_edit(client, project):
    pid = project['id']
    body = {'name': 'Renamed', 'scene': project['scene'], 'revision': project['revision']}
    response = client.put(f'/v1/projects/{pid}', json=body)
    assert response.status_code == 200 and response.json()['revision'] == 2
    assert client.put(f'/v1/projects/{pid}', json=body).status_code == 409
    assert client.get('/v1/projects').json()[0]['name'] == 'Renamed'


def test_queue_is_async_idempotent_and_cancellable(client, project, monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('API must not launch Blender'))
    pid, headers = project['id'], key()
    path = f'/v1/projects/{pid}/jobs'
    r = client.post(path, json={'revision': 1}, headers=headers)
    assert r.status_code == 202 and r.json()['status'] == 'queued'
    assert client.post(path, json={'revision': 1}, headers=headers).json()['id'] == r.json()['id']
    job_id = r.json()['id']
    assert client.get(f'/v1/jobs/{job_id}/files/scene.glb').status_code == 404
    assert client.post(f'/v1/jobs/{job_id}/cancel').json()['status'] == 'cancelled'
    assert client.post(f'/v1/jobs/{job_id}/cancel').json()['status'] == 'cancelled'
    assert len(client.get(path).json()) == 1


def test_pending_and_project_quota(settings):
    with TestClient(create_app(replace(settings, max_pending_jobs=1, max_projects=1))) as c:
        c.headers['Authorization'] = 'Bearer ' + TOKEN
        p = c.post('/v1/projects', json={}, headers=key()).json()
        assert c.post('/v1/projects', json={}, headers=key()).status_code == 429
        path = f"/v1/projects/{p['id']}/jobs"
        assert c.post(path, json={'revision': 1}, headers=key()).status_code == 202
        assert c.post(path, json={'revision': 1}, headers=key()).status_code == 429


def test_restart_preserves_projects_chat_and_jobs(settings):
    with TestClient(create_app(settings)) as c:
        c.headers['Authorization'] = 'Bearer ' + TOKEN
        p = c.post('/v1/projects', json={'name': 'Persistant'}, headers=key()).json()
        pid = p['id']
        proposal = c.post(f'/v1/projects/{pid}/chat', json={'message': 'Ajoute un cube rouge'}, headers=key()).json()
        job = c.post(f"/v1/projects/{pid}/proposals/{proposal['id']}/confirm").json()
    with TestClient(create_app(settings)) as c:
        c.headers['Authorization'] = 'Bearer ' + TOKEN
        assert c.get(f'/v1/projects/{pid}').json()['scene']['objects'][0]['color'] == '#e55b59'
        assert c.get(f'/v1/projects/{pid}/chat').json()[0]['job_id'] == job['id']
        assert c.get(f"/v1/jobs/{job['id']}").json()['status'] == 'queued'


def test_chat_only_plans_confirmation_is_idempotent(client, project):
    pid = project['id']
    headers = key()
    proposal = client.post(f'/v1/projects/{pid}/chat', json={'message': 'Ajoute un cube rouge'}, headers=headers).json()
    assert client.get(f'/v1/projects/{pid}').json()['scene']['objects'] == []
    assert client.get(f'/v1/projects/{pid}/jobs').json() == []
    assert client.post(f'/v1/projects/{pid}/chat', json={'message': 'Ajoute un cube rouge'}, headers=headers).json()['id'] == proposal['id']
    path = f"/v1/projects/{pid}/proposals/{proposal['id']}/confirm"
    first = client.post(path)
    assert first.status_code == 202
    assert client.post(path).json()['id'] == first.json()['id']
    assert client.get(f'/v1/projects/{pid}').json()['revision'] == 2


def test_stale_proposal_and_atomic_quota_rollback(client, project, app):
    pid = project['id']
    proposals = [client.post(f'/v1/projects/{pid}/chat', json={'message': message}, headers=key()).json()
                 for message in ['un cube rouge', 'une sphere bleue']]
    assert client.post(f"/v1/projects/{pid}/proposals/{proposals[0]['id']}/confirm").status_code == 202
    assert client.post(f"/v1/projects/{pid}/proposals/{proposals[1]['id']}/confirm").status_code == 409
    for _ in range(7):
        client.post(f'/v1/projects/{pid}/jobs', json={'revision': 2}, headers=key())
    proposal = client.post(f'/v1/projects/{pid}/chat', json={'message': 'Ajoute un cylindre'}, headers=key()).json()
    assert client.post(f"/v1/projects/{pid}/proposals/{proposal['id']}/confirm").status_code == 429
    assert client.get(f'/v1/projects/{pid}').json()['revision'] == 2


def test_llm_default_spending_gate(settings):
    with TestClient(create_app(replace(settings, agent_mode='llm', llm_api_key='configured-but-not-authorized'))) as c:
        c.headers['Authorization'] = 'Bearer ' + TOKEN
        pid = c.post('/v1/projects', json={}, headers=key()).json()['id']
        assert c.post(f'/v1/projects/{pid}/chat', json={'message': 'un cube'}, headers=key()).status_code == 503
        assert c.get(f'/v1/projects/{pid}/jobs').json() == []


@pytest.mark.parametrize('obj', [
    {'shape': 'torus'}, {'size': 0}, {'size': 21}, {'position': [51, 0, 0]},
    {'color': 'javascript:alert(1)'}, {'code': 'import os'}, {'size': 'NaN'},
])
def test_scene_validation(client, obj):
    assert client.post('/v1/projects', json={'scene': {'objects': [obj]}}, headers=key()).status_code == 422


def test_duplicate_ids_and_unknown_project(client):
    obj = {'id': 'a' * 32}
    assert client.post('/v1/projects', json={'scene': {'objects': [obj, obj]}}, headers=key()).status_code == 422
    assert client.get('/v1/projects/unknown').status_code == 404
    assert client.get('/v1/jobs/not-valid/files/scene.glb').status_code == 404
