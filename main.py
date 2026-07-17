"""Valdez Magic — scan your gym, get your program, ask Valdez anything.

- Email + OTP login (SMTP or dev mode)
- POST /api/scan: video frames -> equipment detection (vision LLM when a key
  is configured; otherwise the client falls back to a manual checklist)
- POST /api/plan: equipment + options -> full weekly workout program
- POST /api/chat: Valdez AI coach (Anthropic / Azure OpenAI when configured,
  built-in exercise-database coach otherwise)
- SQLite storage; optional Azure Blob mirror for uploaded gym videos
"""

from __future__ import annotations

import base64
import hashlib
import json as jsonlib
import os
import re
import secrets
import smtplib
import sqlite3
import time
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from email.mime.text import MIMEText

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import workout_engine as we

APP_NAME = "Valdez Magic"
DATA_DIR = os.environ.get("DATA_DIR", "./data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "valdez.db")
VIDEO_DIR = os.path.join(DATA_DIR, "gymscans")
os.makedirs(VIDEO_DIR, exist_ok=True)

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("VALDEZ_MODEL", "claude-opus-4-8")
AZ_OAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZ_OAI_KEY = os.environ.get("AZURE_OPENAI_KEY", "")
AZ_OAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

AZURE_CONN = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
AZURE_CONTAINER = os.environ.get("AZURE_BLOB_CONTAINER", "gymscans")

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").lower()
SESSION_DAYS = 90
OTP_TTL_MIN = 10
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

app = FastAPI(title=APP_NAME, version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------- db
@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS otps (
                email TEXT PRIMARY KEY, code_hash TEXT NOT NULL, expires_at REAL NOT NULL,
                attempts INTEGER DEFAULT 0, last_sent REAL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS gyms (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, created_at TEXT NOT NULL,
                name TEXT, equipment_json TEXT NOT NULL, video_path TEXT);
            CREATE TABLE IF NOT EXISTS plans (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, created_at TEXT NOT NULL,
                plan_json TEXT NOT NULL);
            """
        )


init_db()


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


# ---------------------------------------------------------------- email + auth (same pattern as Reddy-Fit)
def send_otp_email(to_email: str, code: str) -> bool:
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS):
        return False
    msg = MIMEText(
        f"Your {APP_NAME} login code is: {code}\n\nIt expires in {OTP_TTL_MIN} minutes."
    )
    msg["Subject"] = f"{code} — your {APP_NAME} login code"
    msg["From"] = f"{APP_NAME} <{SMTP_FROM}>"
    msg["To"] = to_email
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)
    return True


class OtpRequest(BaseModel):
    email: str


class OtpVerify(BaseModel):
    email: str
    code: str


def current_user(authorization: str = Header(default="")) -> sqlite3.Row:
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "Login required")
    with db() as conn:
        row = conn.execute(
            """SELECT u.id, u.email FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token = ? AND s.expires_at > ?""",
            (token, time.time()),
        ).fetchone()
    if not row:
        raise HTTPException(401, "Session expired — log in again")
    return row


@app.post("/api/auth/request-otp")
def request_otp(body: OtpRequest):
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email address")
    now = time.time()
    with db() as conn:
        prev = conn.execute("SELECT last_sent FROM otps WHERE email = ?", (email,)).fetchone()
        if prev and now - prev["last_sent"] < 30:
            raise HTTPException(429, "Wait a moment before requesting another code")
        code = f"{secrets.randbelow(1000000):06d}"
        conn.execute(
            """INSERT INTO otps (email, code_hash, expires_at, attempts, last_sent)
               VALUES (?,?,?,0,?)
               ON CONFLICT(email) DO UPDATE SET code_hash=excluded.code_hash,
                 expires_at=excluded.expires_at, attempts=0, last_sent=excluded.last_sent""",
            (email, sha(code), now + OTP_TTL_MIN * 60, now),
        )
    emailed = False
    try:
        emailed = send_otp_email(email, code)
    except Exception:
        emailed = False
    resp = {"sent": True, "emailed": emailed}
    if not emailed:
        resp["dev_otp"] = code
    return resp


@app.post("/api/auth/verify-otp")
def verify_otp(body: OtpVerify):
    email = body.email.strip().lower()
    now = time.time()
    with db() as conn:
        row = conn.execute("SELECT * FROM otps WHERE email = ?", (email,)).fetchone()
        if not row or row["expires_at"] < now:
            raise HTTPException(400, "Code expired — request a new one")
        if row["attempts"] >= 5:
            raise HTTPException(429, "Too many attempts — request a new code")
        if sha(body.code.strip()) != row["code_hash"]:
            conn.execute("UPDATE otps SET attempts = attempts + 1 WHERE email = ?", (email,))
            raise HTTPException(400, "Wrong code — try again")
        conn.execute("DELETE FROM otps WHERE email = ?", (email,))
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        uid = user["id"] if user else secrets.token_hex(16)
        if not user:
            conn.execute("INSERT INTO users (id, email, created_at) VALUES (?,?,?)",
                         (uid, email, datetime.utcnow().isoformat()))
        token = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,?)",
                     (token, uid, now + SESSION_DAYS * 86400))
    return {"token": token, "email": email}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return {"email": user["email"]}


# ---------------------------------------------------------------- LLM helpers
def llm_available() -> str:
    if ANTHROPIC_KEY:
        return "anthropic"
    if AZ_OAI_ENDPOINT and AZ_OAI_KEY:
        return "azure"
    return ""


def _anthropic(messages: list[dict], system: str, images_b64: list[str] | None = None,
               max_tokens: int = 1500) -> str:
    content_msgs = []
    for m in messages:
        content_msgs.append({"role": m["role"], "content": m["content"]})
    if images_b64 and content_msgs:
        parts = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                              "data": img}} for img in images_b64]
        parts.append({"type": "text", "text": content_msgs[-1]["content"]})
        content_msgs[-1] = {"role": "user", "content": parts}
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=jsonlib.dumps({"model": ANTHROPIC_MODEL, "max_tokens": max_tokens,
                            "system": system, "messages": content_msgs}).encode(),
        headers={"Content-Type": "application/json", "x-api-key": ANTHROPIC_KEY,
                 "anthropic-version": "2023-06-01"})
    out = jsonlib.loads(urllib.request.urlopen(req, timeout=90).read())
    return "".join(b.get("text", "") for b in out.get("content", []))


def _azure_oai(messages: list[dict], system: str, images_b64: list[str] | None = None,
               max_tokens: int = 1500) -> str:
    msgs = [{"role": "system", "content": system}]
    for m in messages[:-1]:
        msgs.append({"role": m["role"], "content": m["content"]})
    last = messages[-1]
    if images_b64:
        parts = [{"type": "image_url", "image_url":
                  {"url": f"data:image/jpeg;base64,{img}"}} for img in images_b64]
        parts.append({"type": "text", "text": last["content"]})
        msgs.append({"role": "user", "content": parts})
    else:
        msgs.append(last)
    url = f"{AZ_OAI_ENDPOINT.rstrip('/')}/openai/deployments/{AZ_OAI_DEPLOYMENT}/chat/completions?api-version=2024-06-01"
    req = urllib.request.Request(
        url, data=jsonlib.dumps({"messages": msgs, "max_tokens": max_tokens}).encode(),
        headers={"Content-Type": "application/json", "api-key": AZ_OAI_KEY})
    out = jsonlib.loads(urllib.request.urlopen(req, timeout=90).read())
    return out["choices"][0]["message"]["content"]


def llm(messages: list[dict], system: str, images_b64: list[str] | None = None,
        max_tokens: int = 1500) -> str:
    provider = llm_available()
    if provider == "anthropic":
        return _anthropic(messages, system, images_b64, max_tokens)
    if provider == "azure":
        return _azure_oai(messages, system, images_b64, max_tokens)
    raise RuntimeError("no llm configured")


# ---------------------------------------------------------------- scan
class ScanIn(BaseModel):
    frames: list[str] = Field(default_factory=list)  # base64 jpegs
    video_base64: str | None = None
    gym_name: str | None = None


DETECT_SYSTEM = (
    "You identify gym equipment in photos. Respond with ONLY a JSON array of equipment ids "
    f"from this exact list: {list(we.EQUIPMENT.keys())}. "
    "Include an id only if you can clearly see that equipment in any of the images. No prose."
)


@app.post("/api/scan")
def scan(body: ScanIn, user=Depends(current_user)):
    gym_id = secrets.token_hex(12)
    video_path = None
    if body.video_base64:
        b64 = body.video_base64.split(",")[-1]
        try:
            raw = base64.b64decode(b64)
        except Exception:
            raise HTTPException(400, "Invalid video data")
        if len(raw) > 60_000_000:
            raise HTTPException(400, "Video too large (60MB max)")
        user_dir = os.path.join(VIDEO_DIR, user["id"])
        os.makedirs(user_dir, exist_ok=True)
        video_path = os.path.join(user_dir, f"{gym_id}.webm")
        with open(video_path, "wb") as f:
            f.write(raw)
        _mirror_to_azure(f"{user['id']}/{gym_id}.webm", raw)

    detected: list[str] = []
    ai_used = False
    if body.frames and llm_available():
        try:
            frames = [f.split(",")[-1] for f in body.frames[:6]]
            txt = llm([{"role": "user", "content":
                        "Identify all gym equipment visible across these frames."}],
                      DETECT_SYSTEM, images_b64=frames, max_tokens=400)
            m = re.search(r"\[.*\]", txt, re.S)
            if m:
                cand = jsonlib.loads(m.group(0))
                detected = [c for c in cand if c in we.EQUIPMENT]
                ai_used = True
        except Exception:
            detected = []

    with db() as conn:
        conn.execute(
            "INSERT INTO gyms (id, user_id, created_at, name, equipment_json, video_path) VALUES (?,?,?,?,?,?)",
            (gym_id, user["id"], datetime.utcnow().isoformat(),
             body.gym_name or "My gym", jsonlib.dumps(detected), video_path))
    return {"gym_id": gym_id, "detected": detected, "ai_used": ai_used,
            "equipment_catalog": we.EQUIPMENT}


class GymUpdate(BaseModel):
    equipment: list[str]


@app.post("/api/gyms/{gym_id}/equipment")
def update_gym(gym_id: str, body: GymUpdate, user=Depends(current_user)):
    eq = [e for e in body.equipment if e in we.EQUIPMENT]
    with db() as conn:
        r = conn.execute("SELECT id FROM gyms WHERE id = ? AND user_id = ?",
                         (gym_id, user["id"])).fetchone()
        if not r:
            raise HTTPException(404, "Gym not found")
        conn.execute("UPDATE gyms SET equipment_json = ? WHERE id = ?",
                     (jsonlib.dumps(eq), gym_id))
    return {"gym_id": gym_id, "equipment": eq}


def _mirror_to_azure(name: str, raw: bytes) -> None:
    if not AZURE_CONN:
        return
    try:
        from azure.storage.blob import BlobServiceClient

        service = BlobServiceClient.from_connection_string(AZURE_CONN)
        try:
            service.create_container(AZURE_CONTAINER)
        except Exception:
            pass
        service.get_blob_client(container=AZURE_CONTAINER, blob=name).upload_blob(raw, overwrite=True)
    except Exception:
        pass


# ---------------------------------------------------------------- plan
class PlanIn(BaseModel):
    equipment: list[str]
    days: int = 4
    goal: str = "longevity"
    minutes: int = 45


@app.post("/api/plan")
def plan(body: PlanIn, user=Depends(current_user)):
    eq = [e for e in body.equipment if e in we.EQUIPMENT] or ["bodyweight"]
    p = we.generate_plan(eq, body.days, body.goal, body.minutes)
    pid = secrets.token_hex(12)
    with db() as conn:
        conn.execute("INSERT INTO plans (id, user_id, created_at, plan_json) VALUES (?,?,?,?)",
                     (pid, user["id"], datetime.utcnow().isoformat(), jsonlib.dumps(p)))
    p["plan_id"] = pid
    return p


@app.get("/api/plans/latest")
def latest_plan(user=Depends(current_user)):
    with db() as conn:
        r = conn.execute("SELECT plan_json FROM plans WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
                         (user["id"],)).fetchone()
    if not r:
        raise HTTPException(404, "No plan yet")
    return jsonlib.loads(r["plan_json"])


# ---------------------------------------------------------------- Valdez chat
class ChatIn(BaseModel):
    messages: list[dict]  # [{role, content}]


VALDEZ_SYSTEM = (
    "You are Valdez, an elite personal trainer and longevity coach inside the Valdez Magic app. "
    "You are warm, precise, and practical. Explain like a great coach: short paragraphs, concrete "
    "numbers (sets, reps, rest, RPE), always name the muscles worked, always include a safety cue. "
    "If the user has a plan or equipment list in context, tailor answers to it. You are not a "
    "doctor: for pain or medical issues, advise seeing a professional. Keep answers under 250 words."
)


def _fallback_coach(question: str, context: str) -> str:
    q = question.lower()
    for key, name in we.EQUIPMENT.items():
        if key.replace("_", " ") in q or name.lower() in q:
            exs = [e for e in we.EXERCISES if key in e["equip"]]
            if exs:
                lines = [f"With the {name} you can do:"]
                for e in exs[:4]:
                    lines.append(f"• {e['name']} — targets {', '.join(e['primary'])}. {e['cues']}")
                return "\n".join(lines)
    for e in we.EXERCISES:
        if e["name"].lower() in q:
            return (f"{e['name']}: targets {', '.join(e['primary'])}"
                    f"{' (+' + ', '.join(e['secondary']) + ')' if e['secondary'] else ''}.\n"
                    f"How to: {e['cues']}\nWhy it matters: {e['why']}")
    if any(w in q for w in ["protein", "diet", "eat"]):
        return ("Aim for 1.6–2.0 g of protein per kg of body weight daily, spread over 3-4 meals. "
                "Whole foods first: chicken, fish, eggs, Greek yogurt, dal, paneer, tofu. "
                "Around workouts, any meal with 25-40g protein within a couple hours is plenty.")
    if any(w in q for w in ["rest", "recover", "sore"]):
        return ("Muscles grow between sessions, not during them. Keep 48h between hard sessions for the "
                "same muscle group, sleep 7-9 hours, and walk on rest days. Soreness is normal; sharp "
                "pain is not — if something hurts (not burns), stop and reassess.")
    if any(w in q for w in ["cardio", "run", "vo2"]):
        return ("For longevity: 2-3 zone-2 sessions weekly (30-45 min where you can talk but not sing) "
                "plus one interval day (e.g., 4 × 1 min hard / 2 min easy). VO2 max is the single "
                "strongest predictor of long-term health — treat cardio like an appointment.")
    if any(w in q for w in ["how many day", "days per week", "schedule", "often"]):
        return ("3 days/week full-body is the sweet spot for most people starting out; 4-5 once you're "
                "consistent for a month. The best schedule is the one you'll actually repeat — "
                "generate a plan above and I'll shape it around your life.")
    return ("Great question. Generate your plan above and ask me about any exercise in it — I'll explain "
            "the how and the why. You can also ask about protein, cardio, rest days, or alternatives "
            "for any machine. (Tip: my full AI brain switches on when an API key is configured — "
            "my built-in coaching covers the fundamentals meanwhile.)")


@app.post("/api/chat")
def chat(body: ChatIn, user=Depends(current_user)):
    msgs = [m for m in body.messages if m.get("role") in ("user", "assistant")][-12:]
    if not msgs:
        raise HTTPException(400, "Say something to Valdez")
    with db() as conn:
        planrow = conn.execute(
            "SELECT plan_json FROM plans WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (user["id"],)).fetchone()
        gymrow = conn.execute(
            "SELECT equipment_json FROM gyms WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (user["id"],)).fetchone()
    context = ""
    if gymrow:
        eq = jsonlib.loads(gymrow["equipment_json"])
        context += f"User's gym equipment: {[we.EQUIPMENT.get(e, e) for e in eq]}. "
    if planrow:
        p = jsonlib.loads(planrow["plan_json"])
        context += (f"User's current plan: {p['days_per_week']} days/week, {p['goal']}, "
                    f"{p['session_minutes']} min sessions. "
                    f"Days: {[d['title'] for d in p['week']]}.")
    if llm_available():
        try:
            reply = llm(msgs, VALDEZ_SYSTEM + ("\nContext: " + context if context else ""))
            return {"reply": reply, "ai": True}
        except Exception:
            pass
    return {"reply": _fallback_coach(msgs[-1]["content"], context), "ai": False}


# ---------------------------------------------------------------- admin (email set via env only)
@app.get("/api/admin/stats")
def admin_stats(user=Depends(current_user)):
    if not ADMIN_EMAIL or user["email"].lower() != ADMIN_EMAIL:
        raise HTTPException(403, "Not authorized")
    with db() as conn:
        users = [dict(r) for r in conn.execute(
            "SELECT email, created_at FROM users ORDER BY created_at DESC LIMIT 200").fetchall()]
        gyms = conn.execute("SELECT COUNT(*) FROM gyms").fetchone()[0]
        plans = conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0]
    return {"total_users": len(users), "gyms_scanned": gyms, "plans_generated": plans,
            "recent_users": users}


@app.delete("/api/admin/users/{email}")
def admin_delete_user(email: str, user=Depends(current_user)):
    if not ADMIN_EMAIL or user["email"].lower() != ADMIN_EMAIL:
        raise HTTPException(403, "Not authorized")
    email = email.lower()
    with db() as conn:
        r = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if not r:
            raise HTTPException(404, "No such user")
        uid = r["id"]
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM gyms WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM plans WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    return {"deleted": email}


# ---------------------------------------------------------------- misc
@app.get("/api/health")
def health():
    with db() as conn:
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        plans = conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0]
    return {"status": "ok", "app": APP_NAME, "users": users, "plans": plans,
            "email_configured": bool(SMTP_HOST and SMTP_USER and SMTP_PASS),
            "ai_provider": llm_available() or "built-in coach",
            "azure_blob": bool(AZURE_CONN)}


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
