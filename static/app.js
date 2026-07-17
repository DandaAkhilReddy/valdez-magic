/* Valdez Magic — auth, gym scan, plan, Valdez chat */

const $ = (id) => document.getElementById(id);
let TOKEN = localStorage.getItem("vz_token") || "";
let CATALOG = {};      // equipment id -> label
let selected = new Set();
let gymId = null;
let currentPlan = null;
let chatHistory = [];

/* ================= api ================= */
async function api(path, opts = {}) {
  opts.headers = Object.assign({"Content-Type": "application/json"}, opts.headers || {});
  if (TOKEN) opts.headers["Authorization"] = "Bearer " + TOKEN;
  const r = await fetch(path, opts);
  if (r.status === 401) { showLogin(); throw new Error("auth"); }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "Request failed");
  return r.json();
}

/* ================= auth ================= */
function showLogin() {
  TOKEN = ""; localStorage.removeItem("vz_token");
  $("login-panel").classList.remove("hidden");
  $("app").classList.add("hidden");
  $("user-chip").classList.add("hidden");
  $("chat-fab").classList.add("hidden");
}

function showApp(email) {
  $("login-panel").classList.add("hidden");
  $("app").classList.remove("hidden");
  $("user-chip").classList.remove("hidden");
  $("chat-fab").classList.remove("hidden");
  $("user-email").textContent = email;
  loadLatestPlan();
}

$("btn-send-otp").addEventListener("click", async () => {
  const email = $("login-email").value.trim();
  $("auth-msg").textContent = "Sending…";
  try {
    const r = await api("/api/auth/request-otp", {method: "POST", body: JSON.stringify({email})});
    $("step-email").classList.add("hidden");
    $("step-otp").classList.remove("hidden");
    $("otp-email-label").textContent = email;
    $("auth-msg").textContent = r.emailed
      ? "Code sent — check your inbox."
      : `Your code: ${r.dev_otp} (email not configured — code shown here)`;
    $("login-otp").focus();
  } catch (e) { $("auth-msg").textContent = "⚠️ " + e.message; }
});
$("btn-verify-otp").addEventListener("click", async () => {
  try {
    const r = await api("/api/auth/verify-otp", {method: "POST",
      body: JSON.stringify({email: $("login-email").value.trim(), code: $("login-otp").value.trim()})});
    TOKEN = r.token; localStorage.setItem("vz_token", TOKEN);
    $("auth-msg").textContent = "";
    showApp(r.email);
  } catch (e) { $("auth-msg").textContent = "⚠️ " + e.message; }
});
$("login-email").addEventListener("keydown", (e) => { if (e.key === "Enter") $("btn-send-otp").click(); });
$("login-otp").addEventListener("keydown", (e) => { if (e.key === "Enter") $("btn-verify-otp").click(); });
$("btn-back-email").addEventListener("click", (e) => {
  e.preventDefault();
  $("step-otp").classList.add("hidden");
  $("step-email").classList.remove("hidden");
});
$("btn-logout").addEventListener("click", () => showLogin());

/* ================= scan ================= */
async function extractFrames(file, n = 6) {
  const url = URL.createObjectURL(file);
  const v = document.createElement("video");
  v.src = url; v.muted = true; v.playsInline = true;
  await new Promise((res, rej) => { v.onloadedmetadata = res; v.onerror = rej; });
  const dur = v.duration || 10;
  const canvas = document.createElement("canvas");
  const scale = Math.min(1, 640 / v.videoWidth);
  canvas.width = Math.round(v.videoWidth * scale);
  canvas.height = Math.round(v.videoHeight * scale);
  const ctx = canvas.getContext("2d");
  const frames = [];
  for (let i = 0; i < n; i++) {
    const t = (dur * (i + 0.5)) / n;
    await new Promise((res) => { v.onseeked = res; v.currentTime = Math.min(t, dur - 0.05); });
    ctx.drawImage(v, 0, 0, canvas.width, canvas.height);
    frames.push(canvas.toDataURL("image/jpeg", 0.7));
  }
  URL.revokeObjectURL(url);
  return frames;
}

function fileToDataURL(file) {
  return new Promise((res) => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(file); });
}

$("video-input").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  $("scan-status").textContent = "🔍 Reading your video and sampling frames…";
  $("scan-preview").src = URL.createObjectURL(file);
  $("scan-preview").classList.remove("hidden");
  try {
    const frames = await extractFrames(file);
    $("scan-status").textContent = "🧠 Valdez is identifying your equipment…";
    const payload = {frames};
    if (file.size <= 55 * 1024 * 1024) payload.video_base64 = await fileToDataURL(file);
    const r = await api("/api/scan", {method: "POST", body: JSON.stringify(payload)});
    gymId = r.gym_id;
    CATALOG = r.equipment_catalog;
    selected = new Set(r.detected);
    if (r.ai_used) {
      $("detect-badge").textContent = `AI found ${r.detected.length} item${r.detected.length === 1 ? "" : "s"}`;
      $("detect-badge").classList.remove("hidden");
      $("scan-status").textContent = `✅ Scan complete — Valdez spotted ${r.detected.length} equipment type(s). Confirm below.`;
    } else {
      $("scan-status").textContent = "✅ Video saved. AI detection is warming up — tap your equipment below (takes 20 seconds).";
    }
    renderEquipGrid();
    revealFlow();
  } catch (err) {
    $("scan-status").textContent = "⚠️ " + err.message;
  }
});

$("btn-skip-scan").addEventListener("click", async () => {
  try {
    const r = await api("/api/scan", {method: "POST", body: JSON.stringify({frames: []})});
    gymId = r.gym_id;
    CATALOG = r.equipment_catalog;
    selected = new Set(["bodyweight"]);
    $("scan-status").textContent = "No problem — tap everything your gym has:";
    renderEquipGrid();
    revealFlow();
  } catch (e) { $("scan-status").textContent = "⚠️ " + e.message; }
});

function renderEquipGrid() {
  const grid = $("equip-grid");
  grid.innerHTML = "";
  for (const [id, label] of Object.entries(CATALOG)) {
    const d = document.createElement("div");
    d.className = "equip-item" + (selected.has(id) ? " on" : "");
    d.innerHTML = `${label}<span class="tick"> ✓</span>`;
    d.addEventListener("click", () => {
      selected.has(id) ? selected.delete(id) : selected.add(id);
      d.classList.toggle("on");
    });
    grid.appendChild(d);
  }
}

function revealFlow() {
  $("equip-card").classList.remove("hidden");
  $("options-card").classList.remove("hidden");
  $("equip-card").scrollIntoView({behavior: "smooth"});
}

/* ================= plan ================= */
$("btn-generate").addEventListener("click", async () => {
  if (!selected.size) { alert("Pick at least one piece of equipment (or Just my body)."); return; }
  const btn = $("btn-generate");
  btn.disabled = true; btn.textContent = "⚡ Building your program…";
  try {
    if (gymId) await api(`/api/gyms/${gymId}/equipment`, {method: "POST",
      body: JSON.stringify({equipment: [...selected]})});
    currentPlan = await api("/api/plan", {method: "POST", body: JSON.stringify({
      equipment: [...selected],
      days: parseInt($("opt-days").value, 10),
      goal: $("opt-goal").value,
      minutes: parseInt($("opt-minutes").value, 10),
    })});
    renderPlan(currentPlan);
  } catch (e) { alert(e.message); }
  finally { btn.disabled = false; btn.textContent = "⚡ Build My Program"; }
});

async function loadLatestPlan() {
  try {
    currentPlan = await api("/api/plans/latest");
    renderPlan(currentPlan, true);
  } catch { /* no plan yet */ }
}

function musclesBadges(primary, secondary) {
  return primary.map((m) => `<span class="m-badge">${m}</span>`).join("") +
         (secondary || []).map((m) => `<span class="m-badge sec">${m}</span>`).join("");
}

function renderPlan(p, quiet) {
  $("plan-card").classList.remove("hidden");
  $("plan-summary").innerHTML =
    `<strong>${p.days_per_week} days/week · ${p.session_minutes} min/session · ${p.goal}</strong><br>` +
    `Built from your equipment: ${p.equipment_used.join(", ")}.` +
    (p.rest_days.length ? `<br>Rest days: ${p.rest_days.join(", ")} — active recovery (walk!).` : "");
  const tabs = $("day-tabs");
  tabs.innerHTML = "";
  p.week.forEach((d, i) => {
    const b = document.createElement("button");
    b.className = "day-tab" + (i === 0 ? " on" : "");
    b.textContent = `${d.day.slice(0, 3)} · ${d.title}`;
    b.addEventListener("click", () => {
      tabs.querySelectorAll(".day-tab").forEach((t) => t.classList.remove("on"));
      b.classList.add("on");
      renderDay(d);
    });
    tabs.appendChild(b);
  });
  renderDay(p.week[0]);
  $("coach-notes").innerHTML = "<strong>🩺 Valdez's rules for this program:</strong><ul>" +
    p.coach_notes.map((n) => `<li>${n}</li>`).join("") + "</ul>";
  if (!quiet) $("plan-card").scrollIntoView({behavior: "smooth"});
}

function renderDay(d) {
  $("day-detail").innerHTML =
    `<div class="day-muscles"><span class="muted">Today targets:</span> ${musclesBadges(d.muscles_targeted, [])}</div>` +
    `<div class="phase">🔥 Warm-up (5 min): ${d.warmup}</div>` +
    d.exercises.map((ex, i) => `
      <div class="ex">
        <div class="ex-head">
          <strong>${i + 1}. ${ex.name}</strong>
          <span class="setsreps">${ex.sets} sets × ${ex.reps} · rest ${ex.rest}</span>
        </div>
        <div class="muscles">${musclesBadges(ex.primary_muscles, ex.secondary_muscles)}</div>
        <div class="how"><strong>How:</strong> ${ex.how_to}</div>
        <div class="why">Why it matters: ${ex.why_it_matters}</div>
      </div>`).join("") +
    `<div class="phase">🧘 Cooldown (5 min): ${d.cooldown}</div>`;
}

/* ================= Valdez chat ================= */
$("chat-fab").addEventListener("click", () => {
  $("chat-panel").classList.remove("hidden");
  $("chat-fab").classList.add("hidden");
  if (!chatHistory.length) {
    addMsg("valdez", "Hey, I'm Valdez 🩺 — your coach. Ask me anything: \"what does the lat pulldown work?\", \"alternative to bench press?\", \"how much protein?\" — or generate your program above and ask me about any day.");
  }
  $("chat-input").focus();
});
$("chat-close").addEventListener("click", () => {
  $("chat-panel").classList.add("hidden");
  $("chat-fab").classList.remove("hidden");
});

function addMsg(who, text) {
  const d = document.createElement("div");
  d.className = "msg " + who;
  d.textContent = text;
  $("chat-log").appendChild(d);
  $("chat-log").scrollTop = $("chat-log").scrollHeight;
}

async function sendChat() {
  const text = $("chat-input").value.trim();
  if (!text) return;
  $("chat-input").value = "";
  addMsg("user", text);
  chatHistory.push({role: "user", content: text});
  const thinking = document.createElement("div");
  thinking.className = "msg valdez"; thinking.textContent = "…";
  $("chat-log").appendChild(thinking);
  try {
    const r = await api("/api/chat", {method: "POST",
      body: JSON.stringify({messages: chatHistory.slice(-10)})});
    thinking.remove();
    addMsg("valdez", r.reply);
    chatHistory.push({role: "assistant", content: r.reply});
  } catch (e) {
    thinking.remove();
    addMsg("valdez", "⚠️ " + e.message);
  }
}
$("chat-send").addEventListener("click", sendChat);
$("chat-input").addEventListener("keydown", (e) => { if (e.key === "Enter") sendChat(); });

/* ================= boot ================= */
(async () => {
  if (TOKEN) {
    try { const me = await api("/api/me"); showApp(me.email); return; } catch {}
  }
  showLogin();
})();
