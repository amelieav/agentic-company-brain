// Lightweight frontend. Two modes, detected at load:
//   live: a FastAPI backend answers /api/health -> real signed tokens, real key, real agents.
//   demo: static hosting (e.g. GitHub Pages) -> same UI, client-side fake token, and a video where a key would be used.
"use strict";

const $ = (id) => document.getElementById(id);

// Mirrors company_brain.ROLE_PERMISSIONS (display only; the backend enforces it).
const CAPABILITIES = {
  staff: ["knowledge"],
  manager: ["knowledge", "analytics", "action"],
  exec: ["knowledge", "analytics", "action"],
};
const ALL_CAPS = ["knowledge", "analytics", "action"];
const APP_ROLE_TO_ROLE = { "Brain.Staff": "staff", "Brain.Manager": "manager", "Brain.Exec": "exec" };

// Used in demo mode only; in live mode the list comes from the backend.
const DEMO_USERS = [
  { id: "ben", name: "Ben Okafor", upn: "ben.okafor@moonpool.example", title: "Production Operator", roles: ["Brain.Staff"] },
  { id: "priya", name: "Priya Raman", upn: "priya.raman@moonpool.example", title: "Operations Manager", roles: ["Brain.Manager"] },
  { id: "alex", name: "Alex Whitfield", upn: "alex.whitfield@moonpool.example", title: "Finance Director", roles: ["Brain.Exec"] },
];

const PROMPTS = {
  staff: ["What's the fizz test in the QC procedure?", "What's in a Frost Moon cookie?", "What's in the board minutes?"],
  manager: ["Why do cookies turn grey-green?", "Which regions are below target?", "Which accounts are over 60 days overdue, and send the biggest one a payment reminder."],
  exec: ["What did the board decide on capex?", "How much did we spend on spirulina extract in September?", "Summarise the FY26 strategy."],
};

const state = { mode: "demo", token: null, claims: null };

// ---------- helpers ----------
const show = (...ids) => { for (const v of ["login", "key", "app"]) $(v).hidden = !ids.includes(v); };

function decodeClaims(token) {
  const payload = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
  const json = decodeURIComponent(atob(payload).split("").map((c) => "%" + c.charCodeAt(0).toString(16).padStart(2, "0")).join(""));
  return JSON.parse(json);
}
function fakeToken(user) {
  const b64 = (o) => btoa(JSON.stringify(o)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
  const now = Math.floor(Date.now() / 1000);
  return [b64({ alg: "none", typ: "JWT" }),
    b64({ iss: "https://login.mock-entra.local/moonpool-bakehouse/v2.0", aud: "api://company-brain", iat: now, exp: now + 3600,
      sub: user.id, name: user.name, preferred_username: user.upn, roles: user.roles }), "demo-unsigned"].join(".");
}
const roleOf = (claims) => (claims.roles || []).map((r) => APP_ROLE_TO_ROLE[r]).filter(Boolean)
  .sort((a, b) => ["staff", "manager", "exec"].indexOf(b) - ["staff", "manager", "exec"].indexOf(a))[0];

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", ...(state.token ? { Authorization: "Bearer " + state.token } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}
const initials = (name) => name.split(" ").map((p) => p[0]).join("").slice(0, 2);

// ---------- login ----------
async function detectMode() {
  try {
    const ctrl = new AbortController();
    setTimeout(() => ctrl.abort(), 1500);
    const r = await fetch("api/health", { signal: ctrl.signal });
    state.mode = r.ok && (await r.json()).ok ? "live" : "demo";
  } catch { state.mode = "demo"; }
  const b = $("banner");
  b.hidden = false;
  b.textContent = state.mode === "live"
    ? "Live mode: connected to the local backend."
    : "Demo mode: static page with no backend. Everything works up to the point an API key would be used.";
}

async function renderUsers() {
  const users = state.mode === "live" ? await api("api/users") : DEMO_USERS;
  const roleFor = (u) => u.roles ? roleOf({ roles: u.roles }) : null;
  $("users").innerHTML = "";
  for (const u of users) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.innerHTML = `<span class="avatar"></span><span class="who"><b></b><span></span></span><span class="tag"></span>`;
    btn.querySelector(".avatar").textContent = initials(u.name);
    btn.querySelector("b").textContent = u.name;
    btn.querySelector(".who span").textContent = `${u.title} · ${u.upn}`;
    btn.querySelector(".tag").textContent = { sam: "Staff", priya: "Manager", alex: "Exec" }[u.id] || roleFor(u) || "";
    btn.onclick = () => signIn(u);
    li.append(btn);
    $("users").append(li);
  }
}

async function signIn(user) {
  state.token = state.mode === "live" ? (await api("auth/login", { method: "POST", body: { user_id: user.id } })).access_token : fakeToken(user);
  state.claims = decodeClaims(state.token);
  state.claims.role = roleOf(state.claims);
  $("key-who").textContent = `${state.claims.name} (${state.claims.role})`;
  $("key-input").value = "";
  $("key-error").hidden = true;
  show("key");
}

function signOut() {
  if (state.mode === "live" && state.token) api("api/logout", { method: "POST" }).catch(() => {});
  state.token = state.claims = null;
  $("log").innerHTML = "";
  $("approval").hidden = true;
  show("login");
}

// ---------- key ----------
$("key-form").onsubmit = async (e) => {
  e.preventDefault();
  if (state.mode === "demo") {
    $("key-input").value = "";   // never keep what was typed
    const d = $("video-dialog");
    d.showModal();
    return;
  }
  const btn = $("key-form").querySelector("button"); btn.disabled = true;
  try {
    await api("api/key", { method: "POST", body: { api_key: $("key-input").value } });
    $("key-input").value = "";
    enterApp();
  } catch (err) {
    $("key-error").textContent = err.message; $("key-error").hidden = false;
  } finally { btn.disabled = false; }
};
$("demo-video").addEventListener("error", () => {}, true);
document.querySelector("#demo-video source").addEventListener("error", () => { $("video-missing").hidden = false; });
$("key-signout").onclick = signOut;
$("signout").onclick = signOut;

// ---------- app ----------
function enterApp() {
  const c = state.claims;
  $("me").innerHTML = "";
  const name = document.createElement("div");
  name.innerHTML = "<b></b><div class='muted small'></div>";
  name.querySelector("b").textContent = c.name;
  name.querySelector("div").textContent = `${c.preferred_username} · role: ${c.role}`;
  $("me").append(name);
  $("claims").textContent = JSON.stringify({ iss: c.iss, aud: c.aud, sub: c.sub, name: c.name, roles: c.roles, exp: c.exp }, null, 2);
  $("caps").innerHTML = "";
  for (const cap of ALL_CAPS) {
    const li = document.createElement("li");
    li.textContent = cap;
    if (!CAPABILITIES[c.role].includes(cap)) li.className = "off";
    $("caps").append(li);
  }
  $("chips").innerHTML = "";
  for (const p of PROMPTS[c.role]) {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = p; b.onclick = () => { $("msg").value = p; $("msg").focus(); };
    $("chips").append(b);
  }
  $("log").innerHTML = "";
  addMsg("bot", `Hi ${c.name.split(" ")[0]}. You're signed in as ${c.role}. Ask me about Moonpool Bakehouse's sales, costs, policies or reports.`);
  show("app");
  refreshAudit();
}

function addMsg(kind, text) {
  const d = document.createElement("div");
  d.className = "msg " + kind;
  d.textContent = text;          // textContent: model output is never interpreted as HTML
  $("log").append(d);
  $("log").scrollTop = $("log").scrollHeight;
  return d;
}

async function refreshAudit() {
  if (state.mode !== "live") return;
  try {
    const events = await api("api/audit");
    const ol = $("audit");
    ol.innerHTML = "";
    for (const ev of events.slice(-12).reverse()) {
      const li = document.createElement("li");
      const extra = ev.agent || ev.automation || (ev.action && ev.action.automation) || (ev.sources && ev.sources.length + " source(s)") || "";
      li.innerHTML = "<code></code> <span></span>";
      li.querySelector("code").textContent = new Date(ev.ts * 1000).toLocaleTimeString();
      li.querySelector("span").textContent = ev.event + (extra ? ` — ${extra}` : "");
      ol.append(li);
    }
  } catch { /* panel is best-effort */ }
}

function handleOutcome(out) {
  if (out.type === "approval") {
    $("approval-text").textContent = `${out.request.description} → ${out.request.target}`;
    $("approval").hidden = false;
  } else {
    $("approval").hidden = true;
    addMsg("bot", out.text);
  }
}

function setBusy(busy) {
  for (const el of [$("msg"), $("chat-form").querySelector("button"), $("approve"), $("reject")]) el.disabled = busy;
}

async function turn(fn) {
  setBusy(true);
  const thinking = addMsg("bot thinking", "Thinking…");
  try { handleOutcome(await fn()); }
  catch (err) { addMsg("bot err", "Error: " + err.message); }
  finally { thinking.remove(); setBusy(false); refreshAudit(); }
}

$("chat-form").onsubmit = (e) => {
  e.preventDefault();
  const text = $("msg").value.trim();
  if (!text || !$("approval").hidden) return;
  $("msg").value = "";
  addMsg("user", text);
  turn(() => api("api/chat", { method: "POST", body: { message: text } }));
};
$("approve").onclick = () => { addMsg("user", "Approved."); turn(() => api("api/approve", { method: "POST", body: { approved: true } })); };
$("reject").onclick = () => { addMsg("user", "Rejected."); turn(() => api("api/approve", { method: "POST", body: { approved: false } })); };

// ---------- boot ----------
(async () => { await detectMode(); await renderUsers(); show("login"); })();
