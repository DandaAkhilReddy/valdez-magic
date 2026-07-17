"""Integration tests: auth, scan (fake videos + mocked AI), plans, chat, admin."""

from __future__ import annotations

import base64
import json
import os

import main


# ---------------------------------------------------------------- auth
def test_otp_full_flow(client):
    r = client.post("/api/auth/request-otp", json={"email": "flow@example.org"})
    assert r.status_code == 200
    body = r.json()
    assert body["sent"] is True and len(body["dev_otp"]) == 6
    r = client.post("/api/auth/verify-otp", json={"email": "flow@example.org", "code": body["dev_otp"]})
    assert r.status_code == 200 and r.json()["token"]


def test_invalid_email_rejected(client):
    assert client.post("/api/auth/request-otp", json={"email": "not-an-email"}).status_code == 400


def test_wrong_code_rejected_and_attempts_limited(client):
    email = "attempts@example.org"
    code = client.post("/api/auth/request-otp", json={"email": email}).json()["dev_otp"]
    for _ in range(5):
        assert client.post("/api/auth/verify-otp",
                           json={"email": email, "code": "000000"}).status_code == 400
    # 6th attempt: locked out even with the right code
    assert client.post("/api/auth/verify-otp",
                       json={"email": email, "code": code}).status_code == 429


def test_otp_rate_limit(client):
    email = "ratelimit@example.org"
    assert client.post("/api/auth/request-otp", json={"email": email}).status_code == 200
    assert client.post("/api/auth/request-otp", json={"email": email}).status_code == 429


def test_expired_otp(client, monkeypatch):
    email = "expired@example.org"
    code = client.post("/api/auth/request-otp", json={"email": email}).json()["dev_otp"]
    real_time = main.time.time
    monkeypatch.setattr(main.time, "time", lambda: real_time() + (main.OTP_TTL_MIN + 1) * 60)
    assert client.post("/api/auth/verify-otp",
                       json={"email": email, "code": code}).status_code == 400


def test_protected_routes_require_auth(client):
    assert client.get("/api/me").status_code == 401
    assert client.post("/api/plan", json={"equipment": ["dumbbells"]}).status_code == 401
    assert client.post("/api/scan", json={"frames": []}).status_code == 401
    assert client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]}).status_code == 401


def test_bad_token_rejected(client):
    assert client.get("/api/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


# ---------------------------------------------------------------- scan: fake videos
def test_scan_saves_fake_video(client, login, fake_video_b64):
    h, _ = login()
    r = client.post("/api/scan", json={"frames": [], "video_base64": fake_video_b64}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["gym_id"] and body["ai_used"] is False
    assert len(body["equipment_catalog"]) == 20
    # file actually written
    files = []
    for root, _, names in os.walk(os.path.join(os.environ["DATA_DIR"], "gymscans")):
        files += [os.path.join(root, n) for n in names]
    assert any(body["gym_id"] in f for f in files)


def test_scan_multiple_fake_videos_same_user(client, login, fake_video_b64):
    h, _ = login()
    ids = set()
    for _ in range(3):
        r = client.post("/api/scan", json={"frames": [], "video_base64": fake_video_b64}, headers=h)
        assert r.status_code == 200
        ids.add(r.json()["gym_id"])
    assert len(ids) == 3, "each scan gets its own gym record"


def test_scan_rejects_oversized_video(client, login):
    h, _ = login()
    big = "data:video/webm;base64," + base64.b64encode(b"x" * 61_000_000).decode()
    r = client.post("/api/scan", json={"frames": [], "video_base64": big}, headers=h)
    assert r.status_code == 400


def test_scan_rejects_malformed_video(client, login):
    h, _ = login()
    r = client.post("/api/scan", json={"frames": [], "video_base64": "data:video/webm;base64,!!!not-b64!!!"}, headers=h)
    assert r.status_code == 400


# ---------------------------------------------------------------- equipment detection (mocked AI)
def test_detection_with_mocked_llm(client, login, fake_frames, monkeypatch):
    monkeypatch.setattr(main, "llm_available", lambda: "anthropic")
    monkeypatch.setattr(main, "llm", lambda *a, **k:
                        'Here you go: ["dumbbells", "treadmill", "squat_rack"]')
    h, _ = login()
    r = client.post("/api/scan", json={"frames": fake_frames}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["ai_used"] is True
    assert sorted(body["detected"]) == ["dumbbells", "squat_rack", "treadmill"]


def test_detection_filters_hallucinated_equipment(client, login, fake_frames, monkeypatch):
    monkeypatch.setattr(main, "llm_available", lambda: "anthropic")
    monkeypatch.setattr(main, "llm", lambda *a, **k:
                        '["dumbbells", "flux_capacitor", "time_machine"]')
    h, _ = login()
    body = client.post("/api/scan", json={"frames": fake_frames}, headers=h).json()
    assert body["detected"] == ["dumbbells"], "unknown ids must be dropped"


def test_detection_survives_llm_crash(client, login, fake_frames, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("api down")
    monkeypatch.setattr(main, "llm_available", lambda: "anthropic")
    monkeypatch.setattr(main, "llm", boom)
    h, _ = login()
    body = client.post("/api/scan", json={"frames": fake_frames}, headers=h).json()
    assert body["ai_used"] is False and body["detected"] == []


def test_equipment_update_and_validation(client, login):
    h, _ = login()
    gym = client.post("/api/scan", json={"frames": []}, headers=h).json()
    r = client.post(f"/api/gyms/{gym['gym_id']}/equipment",
                    json={"equipment": ["dumbbells", "hovercraft", "bench"]}, headers=h)
    assert r.status_code == 200
    assert sorted(r.json()["equipment"]) == ["bench", "dumbbells"]


def test_cannot_update_another_users_gym(client, login):
    h1, _ = login()
    h2, _ = login()
    gym = client.post("/api/scan", json={"frames": []}, headers=h1).json()
    r = client.post(f"/api/gyms/{gym['gym_id']}/equipment",
                    json={"equipment": ["dumbbells"]}, headers=h2)
    assert r.status_code == 404


# ---------------------------------------------------------------- plans
def test_plan_endpoint_all_options(client, login):
    h, _ = login()
    for days in (3, 4, 5, 6):
        for goal in ("longevity", "strength", "fatloss"):
            r = client.post("/api/plan", json={
                "equipment": ["dumbbells", "bench"], "days": days,
                "goal": goal, "minutes": 45}, headers=h)
            assert r.status_code == 200
            assert len(r.json()["week"]) == days


def test_plan_empty_equipment_defaults_to_bodyweight(client, login):
    h, _ = login()
    r = client.post("/api/plan", json={"equipment": [], "days": 3}, headers=h)
    assert r.status_code == 200
    assert "Just my body (always available)" in r.json()["equipment_used"]


def test_latest_plan_roundtrip(client, login):
    h, _ = login()
    assert client.get("/api/plans/latest", headers=h).status_code == 404
    client.post("/api/plan", json={"equipment": ["kettlebell"], "days": 4}, headers=h)
    r = client.get("/api/plans/latest", headers=h)
    assert r.status_code == 200 and len(r.json()["week"]) == 4


# ---------------------------------------------------------------- chat
def test_chat_fallback_equipment_question(client, login):
    h, _ = login()
    r = client.post("/api/chat", json={"messages": [
        {"role": "user", "content": "what can I do with dumbbells?"}]}, headers=h)
    assert r.status_code == 200
    assert r.json()["ai"] is False and "Dumbbell" in r.json()["reply"]


def test_chat_fallback_protein_and_cardio(client, login):
    h, _ = login()
    for q, kw in [("how much protein?", "protein"), ("cardio for longevity?", "zone")]:
        reply = client.post("/api/chat", json={"messages": [
            {"role": "user", "content": q}]}, headers=h).json()["reply"].lower()
        assert kw in reply


def test_chat_with_mocked_llm(client, login, monkeypatch):
    monkeypatch.setattr(main, "llm_available", lambda: "anthropic")
    monkeypatch.setattr(main, "llm", lambda msgs, system, **k: "Valdez says: lift smart.")
    h, _ = login()
    r = client.post("/api/chat", json={"messages": [
        {"role": "user", "content": "any advice?"}]}, headers=h)
    assert r.json() == {"reply": "Valdez says: lift smart.", "ai": True}


def test_chat_empty_messages_rejected(client, login):
    h, _ = login()
    assert client.post("/api/chat", json={"messages": []}, headers=h).status_code == 400


# ---------------------------------------------------------------- admin
def test_admin_gate(client, login, monkeypatch):
    monkeypatch.setattr(main, "ADMIN_EMAIL", "akhilreddydanda3@gmail.com")
    h_user, _ = login()
    assert client.get("/api/admin/stats", headers=h_user).status_code == 403
    h_admin, _ = login("akhilreddydanda3@gmail.com")
    r = client.get("/api/admin/stats", headers=h_admin)
    assert r.status_code == 200
    assert r.json()["total_users"] >= 2


def test_admin_delete_user(client, login, monkeypatch):
    monkeypatch.setattr(main, "ADMIN_EMAIL", "akhilreddydanda3@gmail.com")
    h_victim, victim_email = login()
    client.post("/api/plan", json={"equipment": ["dumbbells"], "days": 3}, headers=h_victim)
    h_admin, _ = login("akhilreddydanda3@gmail.com")
    r = client.request("DELETE", f"/api/admin/users/{victim_email}", headers=h_admin)
    assert r.status_code == 200
    # victim's session is dead
    assert client.get("/api/me", headers=h_victim).status_code == 401


def test_admin_disabled_when_env_missing(client, login, monkeypatch):
    monkeypatch.setattr(main, "ADMIN_EMAIL", "")
    h, _ = login()
    assert client.get("/api/admin/stats", headers=h).status_code == 403


# ---------------------------------------------------------------- health
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["app"] == "Valdez Magic"
