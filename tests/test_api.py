"""API + auth tests. No network or real OpenAI key: Brain and key validation are stubbed."""
import os
import tempfile
import time
from pathlib import Path

os.environ["AUDIT_FILE"] = str(Path(tempfile.gettempdir()) / "company_brain_test_audit.jsonl")

import jwt
import pytest
from fastapi.testclient import TestClient

import api
import auth


class StubBrain:
    def __init__(self, key, user_id, role):
        self.role, self.events, self.key = role, [], key
        self.asked = []

    def ask(self, text):
        self.asked.append(text)
        if "remind" in text:
            return {"type": "approval", "request": {"description": "d", "target": "t"}}
        return {"type": "reply", "text": f"echo from {self.role}"}

    def resume(self, approved):
        return {"type": "reply", "text": "done" if approved else "rejected"}


@pytest.fixture()
def client(monkeypatch):
    api.SESSIONS.clear()
    monkeypatch.setattr(api, "Brain", StubBrain)
    monkeypatch.setattr(api, "OpenAI", lambda api_key: type("O", (), {"models": type("M", (), {"list": lambda self: []})()})())
    return TestClient(api.app)


def login(client, user):
    r = client.post("/auth/login", json={"user_id": user})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


KEY = {"api_key": "sk-" + "x" * 30}


def test_role_comes_from_token(client):
    for user, role in (("ben", "staff"), ("priya", "manager"), ("alex", "exec")):
        me = client.get("/api/me", headers=login(client, user)).json()
        assert me["role"] == role
    assert "action" not in client.get("/api/me", headers=login(client, "ben")).json()["capabilities"]


def test_requires_valid_token(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_forged_and_expired_tokens_rejected(client):
    claims = {"iss": auth.ISSUER, "aud": auth.AUDIENCE, "sub": "sam", "jti": "x", "name": "S",
              "preferred_username": "s", "roles": ["Brain.Exec"], "exp": int(time.time()) + 600}
    forged = jwt.encode(claims, "wrong-secret", algorithm="HS256")
    assert client.get("/api/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    expired = jwt.encode({**claims, "exp": int(time.time()) - 5}, auth.SECRET, algorithm="HS256")
    assert client.get("/api/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401


def test_body_cannot_override_role(client):
    h = login(client, "ben")
    client.post("/api/key", json=KEY, headers=h)
    # extra "role" field in the body is ignored; the brain's role is the token's
    client.post("/api/chat", json={"message": "hi", "role": "exec"}, headers=h)
    assert api.SESSIONS[next(iter(api.SESSIONS))].brain.role == "staff"


def test_chat_needs_key_then_works(client):
    h = login(client, "priya")
    assert client.post("/api/chat", json={"message": "hi"}, headers=h).status_code == 409
    assert client.post("/api/key", json=KEY, headers=h).json() == {"connected": True}
    assert client.post("/api/chat", json={"message": "hi"}, headers=h).json()["text"] == "echo from manager"


def test_approval_flow(client):
    h = login(client, "priya")
    client.post("/api/key", json=KEY, headers=h)
    assert client.post("/api/chat", json={"message": "remind them"}, headers=h).json()["type"] == "approval"
    assert client.post("/api/chat", json={"message": "again"}, headers=h).status_code == 409  # must resolve first
    assert client.post("/api/approve", json={"approved": True}, headers=h).json()["text"] == "done"
    assert client.post("/api/approve", json={"approved": True}, headers=h).status_code == 409


def test_sessions_are_isolated_and_logout_drops_key(client):
    a, b = login(client, "ben"), login(client, "alex")
    client.post("/api/key", json={"api_key": "sk-" + "a" * 30}, headers=a)
    assert client.get("/api/me", headers=b).json()["connected"] is False
    client.post("/api/logout", headers=a)
    assert not any(s.brain for s in api.SESSIONS.values() if s.claims["sub"] == "ben")


def test_api_key_never_returned(client):
    h = login(client, "sam")
    r = client.post("/api/key", json=KEY, headers=h)
    assert KEY["api_key"] not in r.text
    assert KEY["api_key"] not in client.get("/api/me", headers=h).text
