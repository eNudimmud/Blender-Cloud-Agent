import json
from dataclasses import replace

import httpx
import pytest
from pydantic import ValidationError

from app.agent import guided_plan, llm_plan
from app.models import SceneSpec


def test_guided_multi_turn_edits():
    scene = guided_plan(SceneSpec(), 'Ajoute un cube rouge de taille 2').scene
    assert scene.objects[0].shape == 'cube'
    scene = guided_plan(scene, 'Rends-le bleu').scene
    assert scene.objects[0].color == '#5d9ddd'
    scene = guided_plan(scene, 'Déplace le cube x=2 y=-3 z=1.5').scene
    assert scene.objects[0].position == (2, -3, 1.5)
    scene = guided_plan(scene, 'Change sa taille à 4').scene
    assert scene.objects[0].size == 4


def test_english_and_french_decimal():
    plan = guided_plan(SceneSpec(), 'Add a blue sphere size 2.5 x=3')
    assert plan.scene.objects[0].position == (3, 0, 0)
    plan = guided_plan(plan.scene, 'Change sa taille de 3,5')
    assert plan.scene.objects[0].size == 3.5
    assert guided_plan(plan.scene, 'Supprime la sphère').scene.objects == []


@pytest.mark.parametrize('prompt', [
    'execute Python __import__("os")', 'Ne crée pas de cube', 'Télécharge https://example.com/model.glb',
    'Ajoute un château rouge', 'Ajoute 100 cubes rouges', 'Ajoute un cube et une sphere', 'un cube taille inf',
])
def test_unsupported_is_not_executed(prompt):
    assert guided_plan(SceneSpec(), prompt).scene is None


@pytest.mark.parametrize('prompt', ['un cube taille 100', 'un cube taille 1e300', 'un cube x=99'])
def test_planner_boundaries(prompt):
    with pytest.raises(ValidationError):
        guided_plan(SceneSpec(), prompt)


def test_paid_gate_makes_zero_network_calls(settings):
    def unexpected(request):
        pytest.fail('No paid call is authorized')
    with httpx.Client(transport=httpx.MockTransport(unexpected)) as client:
        with pytest.raises(ValueError, match='autorisation'):
            llm_plan(settings, SceneSpec(), 'un cube', [], client)


def configured(settings):
    return replace(settings, allow_paid_ai=True, llm_url='https://llm.example/v1/chat/completions',
                   llm_api_key='mock-key', llm_model='mock-model')


def test_llm_adapter_with_mock_transport_only(settings):
    plan = guided_plan(SceneSpec(), 'un cube rouge')
    def reply(request):
        body = json.loads(request.content)
        assert body['max_tokens'] == 1800
        assert 'tools' not in body
        return httpx.Response(200, json={'choices': [{'message': {'content': plan.model_dump_json()}}]})
    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        result = llm_plan(configured(settings), SceneSpec(), 'un cube rouge', [], client)
    assert result.scene.objects[0].shape == 'cube'


def test_llm_cannot_smuggle_code(settings):
    def reply(request):
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'summary': 'ok', 'scene': {'objects': [], 'python': 'import os'}})}}]})
    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        with pytest.raises(ValidationError):
            llm_plan(configured(settings), SceneSpec(), 'un cube', [], client)


def test_llm_caps_response(settings):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b'x' * 65537))) as client:
        with pytest.raises(ValueError, match='volumineuse'):
            llm_plan(configured(settings), SceneSpec(), 'un cube', [], client)


@pytest.mark.parametrize('color,expected', [('bleue', '#5d9ddd'), ('verte', '#77caba'),
                                          ('blanche', '#eeeeee'), ('noire', '#333333')])
def test_french_feminine_colors_match_request(color, expected):
    plan = guided_plan(SceneSpec(), f'Ajoute une sphère {color}')
    assert plan.scene.objects[0].color == expected


@pytest.mark.parametrize('message', [
    'Ajoute un cube x=oops', 'un cube x=2.3.4', 'un cube x=1 x=2', 'un cube taille 2.3.4',
    'un cube x=NaN', 'un cube rouge bleu', "N’ajoute aucun cube", "Don't add a cube", 'Never add a cube',
    'Ajoute un cube puis déplace-le x=2',
])
def test_guided_planner_does_not_partially_apply_ambiguous_requests(message):
    scene = guided_plan(SceneSpec(), 'un cube').scene
    assert guided_plan(scene, message).scene is None
    assert len(scene.objects) == 1 and scene.objects[0].position == (0, 0, 0)
