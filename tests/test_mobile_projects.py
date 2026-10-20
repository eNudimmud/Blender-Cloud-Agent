import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import TOKEN, key


def test_portable_project_round_trip_is_a_new_copy(client):
    original = client.post('/v1/projects', json={'name': 'Sphère de JD', 'scene': {'objects': [
        {'shape': 'sphere', 'color': '#5d9ddd', 'position': [3, 0, 1]}
    ]}}, headers=key()).json()
    exported = client.get(f"/v1/projects/{original['id']}/export")
    assert exported.status_code == 200
    assert exported.headers['cache-control'] == 'no-store'
    assert 'attachment' in exported.headers['content-disposition']
    payload = exported.json()
    assert payload['source'] == {'project_id': original['id'], 'revision': 1}
    assert 'jobs' not in payload and 'request_key' not in exported.text and TOKEN not in exported.text
    headers = key()
    copied = client.post('/v1/projects/import', json=payload, headers=headers)
    assert copied.status_code == 201
    assert copied.json()['id'] != original['id']
    assert copied.json()['scene'] == original['scene']
    assert copied.json()['name'] == original['name']
    assert client.post('/v1/projects/import', json=payload, headers=headers).json()['id'] == copied.json()['id']
    assert len(client.get('/v1/projects').json()) == 2
    assert client.get(f"/v1/projects/{copied.json()['id']}/jobs").json() == []


@pytest.mark.parametrize('mutation', [
    {'format_version': 2}, {'format': 'gltf'}, {'code': 'import os'},
    {'project': {'name': 'bad', 'scene': {'objects': [{'shape': 'torus'}]}}},
    {'project': {'name': 'bad', 'scene': {'objects': [{'position': [999, 0, 0]}]}}},
])
def test_import_rejects_unsupported_data_without_modifying_projects(client, project, mutation):
    payload = client.get(f"/v1/projects/{project['id']}/export").json() | mutation
    assert client.post('/v1/projects/import', json=payload, headers=key()).status_code == 422
    assert client.get('/v1/projects').json() == [project]


def test_import_oversize_and_export_auth(client, project):
    assert client.post('/v1/projects/import', content=b'x' * 32769, headers=key()).status_code == 413
    client.headers.pop('Authorization')
    response = client.get(f"/v1/projects/{project['id']}/export")
    assert response.status_code == 401
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_same_import_key_cannot_create_different_data(client, project):
    payload = client.get(f"/v1/projects/{project['id']}/export").json()
    headers = key()
    assert client.post('/v1/projects/import', json=payload, headers=headers).status_code == 201
    payload['project']['name'] = 'A different project'
    assert client.post('/v1/projects/import', json=payload, headers=headers).status_code == 409


def test_validated_export_fits_streamed_import_bound(client):
    project = client.post('/v1/projects', json={'name': '🌿' * 80, 'scene': {'objects': [
        {'name': '🌿' * 40} for _ in range(24)
    ]}}, headers=key()).json()
    portable = client.get(f"/v1/projects/{project['id']}/export").json()
    # Match JSON.stringify's UTF-8 behavior used by the mobile import.
    wire = json.dumps(portable, ensure_ascii=False).encode()
    assert len(wire) < 32768
    assert client.post('/v1/projects/import', content=wire, headers=key() | {'Content-Type': 'application/json'}).status_code == 201


def test_proxy_address_requires_shared_key_and_overrides_no_other_headers(settings):
    proxy_key = 'proxy-private-key-' + 'x' * 32
    with TestClient(create_app(replace(settings, proxy_key=proxy_key))) as client:
        headers = {'X-CSRF-Token': '1'}
        for index in range(5):
            attempt = headers | {'X-Forwarded-For': f'192.0.2.{index}', 'X-BCA-Client-IP': f'192.0.2.{index}'}
            assert client.post('/v1/auth/session', json={'token': 'wrong'}, headers=attempt).status_code == 401
        assert client.post('/v1/auth/session', json={'token': 'wrong'}, headers=headers | {
            'X-BCA-Proxy-Key': 'wrong-key', 'X-BCA-Client-IP': '192.0.2.100'
        }).status_code == 429
        # Only an authenticated proxy may identify an independently rate-limited address.
        signed = headers | {'X-BCA-Proxy-Key': proxy_key, 'X-BCA-Client-IP': '192.0.2.100'}
        response = client.post('/v1/auth/session', json={'token': TOKEN}, headers=signed)
        assert response.status_code == 200
        invalid = headers | {'X-BCA-Proxy-Key': proxy_key, 'X-BCA-Client-IP': 'not-an-ip'}
        assert client.post('/v1/auth/session', json={'token': TOKEN}, headers=invalid).status_code == 429


@pytest.mark.parametrize('origin', ['https://example.com/path', 'https://name:password@example.com',
                                   'https://example.com?query=x', 'https://example.com#fragment', 'https://bad host'])
def test_public_origin_must_be_exact(settings, origin):
    with pytest.raises(ValueError, match='PUBLIC_ORIGIN'):
        with TestClient(create_app(replace(settings, public_origin=origin))):
            pass
