import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

TOKEN = 'test-workspace-secret-' + 'x' * 32


def key(value=None):
    return {'Idempotency-Key': value or uuid.uuid4().hex}


@pytest.fixture
def settings(tmp_path):
    return Settings(data_root=tmp_path, api_token=TOKEN, secure_cookie=False)


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer ' + TOKEN
        yield client


@pytest.fixture
def project(client):
    response = client.post('/v1/projects', json={'name': 'Atelier Android'}, headers=key())
    assert response.status_code == 201
    return response.json()
