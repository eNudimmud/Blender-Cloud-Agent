import json
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agent import guided_plan, llm_plan
from app.main import create_app
from app.models import SceneObject, SceneSpec
from app.store import Store
from tests.conftest import TOKEN, key


def populated(client):
    objects = [SceneObject(name='Premier cube', color='#e55b59'),
               SceneObject(name='Second cube', position=(4, 0, 0), color='#5d9ddd')]
    response = client.post('/v1/projects', headers=key(), json={
        'name': 'Sélection tactile', 'scene': SceneSpec(objects=objects).model_dump(mode='json')})
    assert response.status_code == 201
    return response.json()


def edit(client, project, name):
    response = client.put(f"/v1/projects/{project['id']}", json={
        'revision': project['revision'], 'name': name, 'scene': project['scene']})
    assert response.status_code == 200
    return response.json()


def test_restore_preserves_history_jobs_and_replays_after_further_edit(client):
    project = populated(client)
    pid = project['id']
    project = edit(client, project, 'Nom modifié')
    proposal = client.post(f'/v1/projects/{pid}/chat', headers=key(), json={
        'message': 'Supprime le cube', 'revision': 2, 'object_id': project['scene']['objects'][0]['id']}).json()
    job = client.post(f"/v1/projects/{pid}/proposals/{proposal['id']}/confirm").json()
    assert len(job['scene']['objects']) == 1
    versions = client.get(f'/v1/projects/{pid}/versions').json()
    assert [v['revision'] for v in versions] == [3, 2, 1]
    assert [v['reason'] for v in versions] == ['confirmed', 'edited', 'created']
    assert all('scene' not in v for v in versions)
    source = client.get(f'/v1/projects/{pid}/versions/1').json()
    headers = key()
    body = {'revision': 3, 'source_revision': 1}
    restored = client.post(f'/v1/projects/{pid}/restore', json=body, headers=headers)
    assert restored.status_code == 200
    result = restored.json()
    assert result['revision'] == 4 and result['scene'] == source['scene']
    assert result['name'] == source['name'] == 'Sélection tactile'
    assert client.get(f'/v1/projects/{pid}/jobs').json() == [job]
    metadata = client.get(f'/v1/projects/{pid}/versions/4').json()
    assert metadata['reason'] == 'restored' and metadata['restored_from'] == 1
    latest = edit(client, result, 'Après la restauration')
    # A lost response is replayed even after another edit, without applying the restore again.
    assert client.post(f'/v1/projects/{pid}/restore', json=body, headers=headers).json() == result
    assert client.get(f'/v1/projects/{pid}').json() == latest
    assert client.post(f'/v1/projects/{pid}/restore', json={'revision': 5, 'source_revision': 2}, headers=headers).status_code == 409


def test_restore_conflicts_and_cross_project_versions_are_refused(client, project):
    pid = project['id']
    other = populated(client)
    edit(client, other, 'Autre projet')
    assert client.post(f'/v1/projects/{pid}/restore', json={'revision': 1, 'source_revision': 2}, headers=key()).status_code == 404
    assert client.post(f'/v1/projects/{pid}/restore', json={'revision': 1, 'source_revision': 1}, headers=key()).status_code == 409
    edited = edit(client, project, 'Version actuelle')
    assert client.post(f'/v1/projects/{pid}/restore', json={'revision': 1, 'source_revision': 1}, headers=key()).status_code == 409
    assert client.get(f'/v1/projects/{pid}').json() == edited
    assert len(client.get(f'/v1/projects/{pid}/versions').json()) == 2


def test_restore_invalidates_old_proposals_without_cancelling_existing_jobs(client, project):
    pid = project['id']
    project = edit(client, project, 'Version deux')
    proposal = client.post(f'/v1/projects/{pid}/chat', headers=key(), json={'message': 'un cube'}).json()
    restored = client.post(f'/v1/projects/{pid}/restore', json={'revision': 2, 'source_revision': 1}, headers=key())
    assert restored.status_code == 200
    assert client.post(f"/v1/projects/{pid}/proposals/{proposal['id']}/confirm").status_code == 409
    assert client.get(f'/v1/projects/{pid}/jobs').json() == []


def test_version_quota_rollback_is_atomic(settings):
    with TestClient(create_app(replace(settings, max_pending_jobs=0))) as client:
        client.headers['Authorization'] = 'Bearer ' + TOKEN
        project = populated(client)
        pid = project['id']
        proposal = client.post(f'/v1/projects/{pid}/chat', headers=key(), json={'message': 'un cube'}).json()
        assert client.post(f"/v1/projects/{pid}/proposals/{proposal['id']}/confirm").status_code == 429
        versions = client.get(f'/v1/projects/{pid}/versions').json()
        assert len(versions) == 1 and versions[0]['revision'] == 1
        assert client.get(f'/v1/projects/{pid}').json() == project


def test_history_retention_and_restore_receipt_survive_pruning(client, project, app):
    pid = project['id']
    current = edit(client, project, 'Deux')
    headers = key()
    body = {'revision': 2, 'source_revision': 1}
    restored = client.post(f'/v1/projects/{pid}/restore', json=body, headers=headers).json()
    store = app.state.store
    # Seed many real revisions directly, avoiding consumption of the HTTP write quota.
    with store.connect(write=True) as con:
        for revision in range(4, 105):
            con.execute('UPDATE projects SET revision=?,name=? WHERE id=?', (revision, f'Projet {revision}', pid))
            store.record_version(con, pid, 'edited')
    versions = client.get(f'/v1/projects/{pid}/versions').json()
    assert len(versions) == 100 and versions[0]['revision'] == 104 and versions[-1]['revision'] == 5
    assert client.get(f'/v1/projects/{pid}/versions/1').status_code == 404
    assert client.post(f'/v1/projects/{pid}/restore', json=body, headers=headers).json() == restored
    assert client.get(f'/v1/projects/{pid}').json()['revision'] == 104
    assert current['revision'] == 2


def test_target_selection_changes_only_the_requested_object_and_survives_replay(client):
    project = populated(client)
    pid = project['id']
    first, second = project['scene']['objects']
    body = {'message': 'Change sa couleur en vert', 'revision': 1, 'object_id': first['id']}
    headers = key()
    response = client.post(f'/v1/projects/{pid}/chat', json=body, headers=headers)
    assert response.status_code == 201
    proposal = response.json()
    assert proposal['scene']['objects'][0]['color'] == '#77caba'
    assert proposal['scene']['objects'][1] == second
    assert 'request_fingerprint' not in proposal
    assert client.post(f'/v1/projects/{pid}/chat', json=dict(body, object_id=second['id']), headers=headers).status_code == 409
    confirmed = client.post(f"/v1/projects/{pid}/proposals/{proposal['id']}/confirm")
    assert confirmed.status_code == 202
    assert client.post(f'/v1/projects/{pid}/chat', json=body, headers=headers).json() == dict(proposal, job_id=confirmed.json()['id'])
    assert client.post(f'/v1/projects/{pid}/chat', json=body, headers=key()).status_code == 409


@pytest.mark.parametrize('body', [
    {'object_id': 'a' * 32}, {'revision': 1, 'object_id': 'z' * 32},
    {'revision': 1, 'object_id': 'a' * 32}, {'revision': 0},
])
def test_invalid_selection_is_refused_without_a_proposal(client, project, body):
    pid = project['id']
    response = client.post(f'/v1/projects/{pid}/chat', json={'message': 'Change sa taille à 3', **body}, headers=key())
    assert response.status_code == 422
    assert client.get(f'/v1/projects/{pid}/chat').json() == []


def test_stale_revision_never_reaches_external_planner(settings, monkeypatch):
    monkeypatch.setattr('app.main.llm_plan', lambda *args, **kwargs: pytest.fail('Stale input must not contact a provider'))
    with TestClient(create_app(replace(settings, agent_mode='llm', allow_paid_ai=True))) as client:
        client.headers['Authorization'] = 'Bearer ' + TOKEN
        project = populated(client)
        project = edit(client, project, 'Nouvelle version')
        assert client.post(f"/v1/projects/{project['id']}/chat", headers=key(), json={
            'message': 'Rends-le vert', 'revision': 1, 'object_id': project['scene']['objects'][0]['id']}).status_code == 409


def test_guided_selection_refuses_a_contradictory_shape():
    scene = SceneSpec(objects=[SceneObject(shape='sphere'), SceneObject(shape='cube')])
    plan = guided_plan(scene, 'Déplace le cube x=3', scene.objects[0].id)
    assert plan.scene is None
    plan = guided_plan(scene, 'Supprime cet objet', scene.objects[0].id)
    assert plan.scene.objects == [scene.objects[1]]
    plan = guided_plan(scene, 'Ajoute un cube rouge', scene.objects[0].id)
    assert plan.scene.objects[:2] == scene.objects and len(plan.scene.objects) == 3


def test_llm_cannot_modify_an_unselected_object(settings):
    scene = SceneSpec(objects=[SceneObject(), SceneObject()])
    changed = scene.model_copy(deep=True)
    changed.objects[1].size = 10
    def reply(request):
        payload = json.loads(request.content)
        content = json.loads(payload['messages'][1]['content'])
        assert content['selected_object_id'] == scene.objects[0].id
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({
            'summary': 'Une modification', 'scene': changed.model_dump(mode='json')})}}]})
    configured = replace(settings, allow_paid_ai=True, llm_url='https://mock.example/v1/chat/completions',
                         llm_model='mock-only', llm_api_key='mock-only')
    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        with pytest.raises(ValueError, match='hors de la sélection'):
            llm_plan(configured, scene, 'Change sa taille à 3', [], client, object_id=scene.objects[0].id)


def test_old_database_migrates_concurrently_without_losing_projects_or_pending_requests(settings):
    settings.data_root.mkdir(exist_ok=True)
    path = settings.data_root / 'agent.sqlite3'
    project_id, proposal_id, job_id = '1' * 32, '2' * 32, '3' * 32
    with sqlite3.connect(path) as con:
        con.executescript((Path(__file__).parent / 'fixtures/schema-v1.sql').read_text())
        con.execute('INSERT INTO projects VALUES (?,?,?,?,?,?)', (project_id, 'Avant mise à jour', '{"schema_version":1,"objects":[]}', 3, time.time(), time.time()))
        con.execute('INSERT INTO proposals (id,project_id,base_revision,message,summary,mode,request_key,created_at) VALUES (?,?,?,?,?,?,?,?)',
                    (proposal_id, project_id, 3, 'bonjour', 'Aide', 'rules', 'legacy-request', time.time()))
        con.execute("INSERT INTO jobs (id,project_id,revision,scene,status,request_key,created_at,updated_at) VALUES (?,?,2,?,'queued',?,?,?)",
                    (job_id, project_id, '{"schema_version":1,"objects":[]}', 'legacy-job', time.time(), time.time()))
    command = [sys.executable, '-c',
               'import sys; from pathlib import Path; from app.config import Settings; '
               'from app.store import Store; Store(Settings(data_root=Path(sys.argv[1]))).initialize()',
               str(settings.data_root)]
    processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
    for process in processes:
        _, error = process.communicate(timeout=20)
        assert process.returncode == 0, error
    with TestClient(create_app(settings)) as client:
        client.headers['Authorization'] = 'Bearer ' + TOKEN
        assert client.get(f'/v1/projects/{project_id}').json()['revision'] == 3
        assert client.get(f'/v1/jobs/{job_id}').json()['status'] == 'queued'
        versions = client.get(f'/v1/projects/{project_id}/versions').json()
        assert len(versions) == 1 and versions[0]['reason'] == 'migration' and versions[0]['revision'] == 3
        old = client.post(f'/v1/projects/{project_id}/chat', json={'message': 'bonjour'}, headers=key('legacy-request'))
        assert old.status_code == 201 and old.json()['id'] == proposal_id
        assert client.post(f'/v1/projects/{project_id}/chat', json={'message': 'bonjour', 'revision': 3}, headers=key('legacy-request')).status_code == 409
    with sqlite3.connect(path) as con:
        assert con.execute('PRAGMA user_version').fetchone()[0] == 2


def test_history_and_restore_require_auth_and_cookie_csrf(client, project):
    pid = project['id']
    edit(client, project, 'Deux')
    client.headers.pop('Authorization')
    assert client.get(f'/v1/projects/{pid}/versions').status_code == 401
    assert client.get(f'/v1/projects/{pid}/versions/1').status_code == 401
    assert client.post(f'/v1/projects/{pid}/restore', json={'revision': 2, 'source_revision': 1}, headers=key()).status_code == 401
    assert client.post('/v1/auth/session', json={'token': TOKEN}, headers={'X-CSRF-Token': '1'}).status_code == 200
    assert client.post(f'/v1/projects/{pid}/restore', json={'revision': 2, 'source_revision': 1}, headers=key()).status_code == 403


@pytest.mark.parametrize('same_key', [True, False])
def test_concurrent_restore_requests_create_one_version(client, project, same_key):
    pid = project['id']
    edit(client, project, 'Deux')
    shared = key()
    def restore(_):
        return client.post(f'/v1/projects/{pid}/restore', json={'revision': 2, 'source_revision': 1},
                           headers=shared if same_key else key())
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(restore, range(4)))
    if same_key:
        assert all(r.status_code == 200 for r in responses)
        assert all(r.json() == responses[0].json() for r in responses)
    else:
        assert sorted(r.status_code for r in responses) == [200, 409, 409, 409]
    assert client.get(f'/v1/projects/{pid}').json()['revision'] == 3
    assert len(client.get(f'/v1/projects/{pid}/versions').json()) == 3
    assert client.get(f'/v1/projects/{pid}/jobs').json() == []


def test_restore_quota_does_not_partially_change_project_or_history(client, project, app):
    pid = project['id']
    current = edit(client, project, 'Deux')
    with app.state.store.connect(write=True) as con:
        con.executemany('INSERT INTO restore_keys VALUES (?,?,?,?)',
                        [(pid, f'old-request-{i}', 'old-fingerprint', '{}') for i in range(2000)])
    assert client.post(f'/v1/projects/{pid}/restore', json={'revision': 2, 'source_revision': 1}, headers=key()).status_code == 429
    assert client.get(f'/v1/projects/{pid}').json() == current
    assert len(client.get(f'/v1/projects/{pid}/versions').json()) == 2


def test_future_database_schema_is_refused_without_downgrading_it(settings):
    settings.data_root.mkdir(exist_ok=True)
    with sqlite3.connect(settings.data_root / 'agent.sqlite3') as con:
        con.executescript('CREATE TABLE future_feature (value TEXT); PRAGMA user_version=99;')
    with pytest.raises(RuntimeError, match='Unsupported database schema'):
        Store(settings).initialize()
    with sqlite3.connect(settings.data_root / 'agent.sqlite3') as con:
        assert con.execute('PRAGMA user_version').fetchone()[0] == 99
        assert con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [('future_feature',)]
