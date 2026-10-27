"""
Integration Tests for Manager Hub REST API and Dashboard Endpoints
"""

import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from hub.server import create_app

@pytest.fixture
def client(tmp_path):
    db_file = tmp_path / "test_hub.db"
    audio_dir = tmp_path / "audio"
    static_dir = Path(__file__).parent.parent / "hub" / "static"
    app = create_app(db_path=db_file, audio_dir=audio_dir, static_dir=static_dir)
    return TestClient(app)

def test_auth_status_initial(client):
    res = client.get("/api/auth/status")
    assert res.status_code == 200
    data = res.json()
    assert data["has_password"] is False
    assert data["is_authenticated"] is True

def test_auth_setup_and_login(client):
    # 1. Setup password
    res = client.post("/api/auth/setup", json={"password": "ManagerOffice2026!"})
    assert res.status_code == 200
    assert "hub_session" in client.cookies

    # 2. Check status (now has password and is authenticated)
    status_res = client.get("/api/auth/status")
    assert status_res.json()["has_password"] is True
    assert status_res.json()["is_authenticated"] is True

    # 3. Logout
    client.post("/api/auth/logout")
    status_after_logout = client.get("/api/auth/status")
    assert status_after_logout.json()["is_authenticated"] is False

    # 4. Login with bad password
    bad_login = client.post("/api/auth/login", json={"password": "wrong"})
    assert bad_login.status_code == 401

    # 5. Login with correct password
    good_login = client.post("/api/auth/login", json={"password": "ManagerOffice2026!"})
    assert good_login.status_code == 200
    assert "hub_session" in client.cookies

def test_pairing_api_workflow(client):
    # Setup auth
    client.post("/api/auth/setup", json={"password": "ManagerOffice2026!"})

    # Get pairing code
    code_res = client.get("/api/pairing/code")
    assert code_res.status_code == 200
    pairing_code = code_res.json()["pairing_code"]
    assert len(pairing_code) == 6

    # Attempt pair with invalid code
    bad_pair = client.post("/api/pair", json={
        "pairing_code": "000000",
        "device_id": "DEV-TEST-01",
        "name": "Reception Desk"
    })
    assert bad_pair.status_code == 400

    # Pair with correct code
    good_pair = client.post("/api/pair", json={
        "pairing_code": pairing_code,
        "device_id": "DEV-TEST-01",
        "name": "Reception Desk",
        "hostname": "reception-pc"
    })
    assert good_pair.status_code == 200
    pair_data = good_pair.json()
    assert pair_data["status"] == "paired"
    assert len(pair_data["auth_token"]) == 64

    # Device should now be listed
    devices_res = client.get("/api/devices")
    assert devices_res.status_code == 200
    devs = devices_res.json()
    assert len(devs) == 1
    assert devs[0]["device_id"] == "DEV-TEST-01"
    assert devs[0]["name"] == "Reception Desk"

def test_static_index_serving(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Keystone Audio Hub" in res.text
    assert "<canvas id=\"liveVisualizer\"" in res.text
