/**
 * dashboard.js — Real-time rescue boat dashboard logic
 *
 * Works in BOTH deployment modes:
 *   1. All-in-one (boat serves the dashboard): connects SocketIO to same host
 *   2. Split PC/Boat: fetches /config to get the boat's SocketIO URL, then
 *      connects directly to the boat for real-time events
 */

/* ── Determine boat SocketIO URL ─────────────────────────────────────────── */
async function getBoatSocketUrl() {
  try {
    const res  = await fetch("/config");
    const data = await res.json();
    return data.socketio_url || window.location.origin;
  } catch {
    // All-in-one mode — SocketIO is on the same host as the page
    return window.location.origin;
  }
}

/* ── Bootstrap ───────────────────────────────────────────────────────────── */
getBoatSocketUrl().then(socketUrl => {
  initDashboard(socketUrl);
});

function initDashboard(socketUrl) {

/* ── SocketIO connection ─────────────────────────────────────────────────── */
const socket = io(socketUrl, { transports: ["websocket", "polling"] });

const connStatus  = document.getElementById("conn-status");
const connLabel   = document.getElementById("conn-label");
const modeBadge   = document.getElementById("mode-badge");
const modeLabel   = document.getElementById("mode-label");
const serialLabel = document.getElementById("serial-label");

socket.on("connect", () => {
  connLabel.textContent = "Connected";
  connStatus.classList.remove("offline");
  logEvent("system", `Connected → ${socketUrl}`);
  fetchStatus();
});

socket.on("disconnect", () => {
  connLabel.textContent = "Disconnected";
  connStatus.classList.add("offline");
  logEvent("system", "Lost connection to boat server.");
});

/* ── Detection event ─────────────────────────────────────────────────────── */
const markersLayer   = document.getElementById("markers-layer");
const mapWrap        = document.getElementById("map-wrap");
const dangerAlert    = document.getElementById("danger-alert");
const statPersons    = document.getElementById("stat-persons-val");
const statDanger     = document.getElementById("stat-danger-val");
const statDangerCard = document.getElementById("stat-danger");

socket.on("detection", (data) => {
  const persons = data.persons || [];
  updateMapMarkers(persons);
  updateStats(persons);
  updateDangerAlert(persons);
});

socket.on("status", (data) => {
  if (data.mode) applyModeUI(data.mode);
});

/* ── Map markers ─────────────────────────────────────────────────────────── */
function updateMapMarkers(persons) {
  markersLayer.innerHTML = "";
  persons.forEach((p, i) => {
    const el = document.createElement("div");
    el.className = `person-marker ${p.in_danger ? "danger" : "safe"}`;
    el.style.left = `${p.rel_x * 100}%`;
    el.style.top  = `${p.rel_y * 100}%`;
    el.title = `Person ${i + 1}: conf=${p.confidence} ${p.in_danger ? "⚠ DANGER" : "safe"}`;
    markersLayer.appendChild(el);
    if (p.in_danger) {
      logEvent("danger", `⚠ Person ${i + 1} in danger zone! (conf ${p.confidence})`);
    }
  });
}

function updateStats(persons) {
  const dangerCount = persons.filter(p => p.in_danger).length;
  statPersons.textContent = persons.length;
  statDanger.textContent  = dangerCount;
}

function updateDangerAlert(persons) {
  const hasDanger = persons.some(p => p.in_danger);
  dangerAlert.classList.toggle("hidden", !hasDanger);
  statDangerCard.classList.toggle("active", hasDanger);
}

/* ── Mode switching ──────────────────────────────────────────────────────── */
const modeBtns = document.querySelectorAll(".mode-btn");
const dropBtn  = document.getElementById("drop-btn");
const dropHint = document.getElementById("drop-hint");
const statMode = document.getElementById("stat-mode-val");

modeBtns.forEach(btn => {
  btn.addEventListener("click", () => {
    const mode = btn.dataset.mode;
    fetch("/api/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    })
    .then(r => r.json())
    .then(d => {
      if (d.ok) {
        applyModeUI(mode);
        logEvent("mode", `Mode → ${mode.toUpperCase().replace("_", " ")}`);
      } else {
        logEvent("system", `Mode error: ${d.error}`);
      }
    })
    .catch(() => logEvent("system", "Failed to change mode (boat unreachable?)."));
  });
});

function applyModeUI(mode) {
  modeBtns.forEach(b => b.classList.toggle("active", b.dataset.mode === mode));
  modeLabel.textContent = mode.replace("_", " ").toUpperCase();
  statMode.textContent  = mode.toUpperCase();
  const isSupply = mode === "supply_drop";
  dropBtn.disabled = !isSupply;
  dropHint.textContent = isSupply
    ? "Navigate to target, then drop supply."
    : "Enable Supply Drop mode first.";
}

/* ── Target setting (click on map) ──────────────────────────────────────── */
const targetMarker = document.getElementById("target-marker");
const coordX = document.getElementById("coord-x");
const coordY = document.getElementById("coord-y");

mapWrap.addEventListener("click", (e) => {
  const rect  = mapWrap.getBoundingClientRect();
  const rel_x = parseFloat(((e.clientX - rect.left) / rect.width).toFixed(3));
  const rel_y = parseFloat(((e.clientY - rect.top)  / rect.height).toFixed(3));

  targetMarker.style.left = `${rel_x * 100}%`;
  targetMarker.style.top  = `${rel_y * 100}%`;
  targetMarker.classList.remove("hidden");
  coordX.textContent = rel_x.toFixed(2);
  coordY.textContent = rel_y.toFixed(2);

  fetch("/api/target", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rel_x, rel_y }),
  })
  .then(r => r.json())
  .then(d => {
    if (d.ok) logEvent("action", `Target → (${rel_x.toFixed(2)}, ${rel_y.toFixed(2)})`);
  })
  .catch(() => logEvent("system", "Failed to set target."));
});

/* ── Clear map ───────────────────────────────────────────────────────────── */
document.getElementById("clear-map-btn").addEventListener("click", () => {
  markersLayer.innerHTML = "";
  targetMarker.classList.add("hidden");
  coordX.textContent = "—";
  coordY.textContent = "—";
  logEvent("system", "Map cleared.");
});

/* ── Supply drop ─────────────────────────────────────────────────────────── */
dropBtn.addEventListener("click", () => {
  if (!confirm("Confirm supply drop? The servo will release payload.")) return;
  fetch("/api/drop", { method: "POST" })
    .then(r => r.json())
    .then(d => { if (d.ok) logEvent("action", "📦 Supply drop triggered!"); })
    .catch(() => logEvent("system", "Supply drop failed."));
});

/* ── Emergency stop ──────────────────────────────────────────────────────── */
document.getElementById("stop-btn").addEventListener("click", () => {
  fetch("/api/mode", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: "scout" }),
  })
  .then(r => r.json())
  .then(d => {
    if (d.ok) { applyModeUI("scout"); logEvent("action", "🛑 Emergency stop!"); }
  })
  .catch(() => logEvent("system", "Emergency stop failed."));
});

/* ── Initial status fetch ────────────────────────────────────────────────── */
function fetchStatus() {
  fetch("/api/status")
    .then(r => r.json())
    .then(d => {
      if (d.mode) applyModeUI(d.mode);
      if (d.serial_dry_run !== undefined) {
        const dry = d.serial_dry_run;
        serialLabel.textContent = dry ? "Serial: DRY-RUN" : "Serial: OK";
        document.getElementById("stat-serial-val").textContent = dry ? "DRY-RUN" : "OK";
        logEvent("system", dry
          ? "Arduino serial: DRY-RUN (no MCU connected)"
          : "Arduino serial: connected ✓");
      }
    })
    .catch(() => logEvent("system", "Could not reach boat API."));
}

/* ── Event log ───────────────────────────────────────────────────────────── */
const logEntries = document.getElementById("log-entries");

function logEvent(type, message) {
  const now = new Date().toLocaleTimeString("en-GB", { hour12: false });
  const el  = document.createElement("div");
  el.className   = `log-entry log-${type}`;
  el.textContent = `[${now}] ${message}`;
  logEntries.prepend(el);
  while (logEntries.children.length > 80) logEntries.removeChild(logEntries.lastChild);
}

} // end initDashboard
