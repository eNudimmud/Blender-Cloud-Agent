from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health():
    assert client.get("/health").json() == {"status": "ok"}

def test_validation():
    response = client.post("/v1/scenes", json={"shape": "torus", "size": 2})
    assert response.status_code == 422

def test_invalid_artifact_id():
    assert client.get("/v1/scenes/not-valid/files/scene.glb").status_code == 404

def test_mobile_page():
    response = client.get("/")
    assert response.status_code == 200
    assert "BLENDER CLOUD" in response.text
