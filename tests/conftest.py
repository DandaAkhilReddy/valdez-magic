"""Test fixtures for Valdez Magic."""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

# Point the app at a throwaway data dir BEFORE importing it.
_TMP = tempfile.mkdtemp(prefix="valdez-test-")
os.environ["DATA_DIR"] = _TMP
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    return TestClient(main.app)


_counter = {"n": 0}


@pytest.fixture()
def login(client):
    """Factory: returns (headers, email) for a fresh logged-in user."""

    def _login(email: str | None = None):
        _counter["n"] += 1
        email = email or f"user{_counter['n']}@example.org"
        r = client.post("/api/auth/request-otp", json={"email": email})
        assert r.status_code == 200, r.text
        code = r.json()["dev_otp"]
        r = client.post("/api/auth/verify-otp", json={"email": email, "code": code})
        assert r.status_code == 200, r.text
        return {"Authorization": "Bearer " + r.json()["token"]}, email

    return _login


FAKE_WEBM = b"\x1aE\xdf\xa3" + b"valdez-fake-gym-video" * 200  # EBML magic + filler


@pytest.fixture()
def fake_video_b64() -> str:
    import base64

    return "data:video/webm;base64," + base64.b64encode(FAKE_WEBM).decode()


@pytest.fixture()
def fake_frames() -> list[str]:
    import base64

    jpg = b"\xff\xd8\xff\xe0" + b"frame" * 50
    return ["data:image/jpeg;base64," + base64.b64encode(jpg + bytes([i])).decode()
            for i in range(6)]
