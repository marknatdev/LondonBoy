/**
 * dashboard.js — All-in-one rescue boat dashboard
 *
 * Connects to the boat server directly (same host).
 * - SocketIO for real-time detection events and status
 * - Native WebSocket (/ws) for live MJPEG video stream
 */

(function () {
  "use strict";

  const origin = window.location.origin;

  // ── SocketIO ──────────────────────────────────────────────────────────────
  const socket = io(origin, { transports: ["websocket", "polling"] });

  const connStatus  = document.getElementById("conn-status");
  const connLabel   = document.getElementById("conn-label");
  const modeLabel   = document.getElementById("mode-label");
  const serialLabel = document.getElementById("serial-label");
  const liveBadge   = document.getElementById("live-badge");

  socket.on("connect", () => {
    connLabel.textContent = "Connected";
    connStatus.classList.remove("offline");
    logEvent("system", "Connected to boat server");
    fetchStatus();
    connectVideoStream();
  });

  socket.on("disconnect", () => {
    connLabel.textContent = "Disconnected";
    connStatus.classList.add("offline");
    logEvent("system", "Lost connection to boat server");
  });

  // ── Video WebSocket Stream ────────────────────────────────────────────────
  const cameraFeed = document.getElementById("camera-feed");
  let videoWs = null;

  function connectVideoStream() {
    const wsProto = location.protocol === "https:" ? "wss:" : "ws:";
    videoWs = new WebSocket(`${wsProto}//${location.host}/ws`);
    videoWs.binaryType = "blob";

    videoWs.onopen = () => {
      liveBadge.textContent = "LIVE";
      liveBadge.style.opacity = "1";
      logEvent("system", "Video stream connected");
    };

    videoWs.onmessage = (e) => {
      const url = URL.createObjectURL(e.data);
      cameraFeed.onload = () => URL.revokeObjectURL(url);
      cameraFeed.src = url;
    };

    videoWs.onclose = () => {
      liveBadge.textContent = "OFFLINE";
      liveBadge.style.opacity = "0.4";
      // Reconnect after 3 seconds
      setTimeout(connectVideoStream, 3000);
    };
  }

  // ── Detection Events ──────────────────────────────────────────────────────
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

  function updateMapMarkers(persons) {
    markersLayer.innerHTML = "";
    persons.forEach((p, i) => {
      const el = document.createElement("div");
      el.className = `person-marker ${p.in_danger ? "danger" : "safe"}`;
      el.style.left = `${p.rel_x * 100}%`;
      el.style.top  = `${p.rel_y * 100}%`;
      el.title = `Person ${i + 1}: conf=${p.confidence} ${p.in_danger ? "⚠ DANGER" : "safe"}`;
      markersLayer.appendChild(el);
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

  // ── Mode Switching ────────────────────────────────────────────────────────
  const modeBtns = document.querySelectorAll(".mode-btn");
  const dropBtn  = document.getElementById("drop-btn");
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
        }
      })
      .catch(() => logEvent("system", "Failed to change mode."));
    });
  });

  function applyModeUI(mode) {
    modeBtns.forEach(b => b.classList.toggle("active", b.dataset.mode === mode));
    modeLabel.textContent = mode.replace("_", " ").toUpperCase();
    statMode.textContent  = mode.toUpperCase();
    const isSupply = mode === "supply_drop";
    dropBtn.disabled = !isSupply;
  }

  // ── Target Setting (click on map) ─────────────────────────────────────────
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
      if (d.ok) logEvent("action", `Waypoint → (${rel_x.toFixed(2)}, ${rel_y.toFixed(2)})`);
    })
    .catch(() => logEvent("system", "Failed to set waypoint."));
  });

  // ── Clear Map ─────────────────────────────────────────────────────────────
  document.getElementById("clear-map-btn").addEventListener("click", () => {
    markersLayer.innerHTML = "";
    targetMarker.classList.add("hidden");
    coordX.textContent = "—";
    coordY.textContent = "—";
    logEvent("system", "Radar cleared.");
  });

  // ── Supply Drop ───────────────────────────────────────────────────────────
  dropBtn.addEventListener("click", () => {
    if (!confirm("Confirm supply drop? The servo will release payload.")) return;
    fetch("/api/drop", { method: "POST" })
      .then(r => r.json())
      .then(d => { if (d.ok) logEvent("action", "📦 Supply drop triggered!"); })
      .catch(() => logEvent("system", "Supply drop failed."));
  });

  // ── Emergency Stop ────────────────────────────────────────────────────────
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

  // ── Status Fetch ──────────────────────────────────────────────────────────
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
            ? "Arduino serial: DRY-RUN (no MCU)"
            : "Arduino serial: connected ✓");
        }
      })
      .catch(() => logEvent("system", "Could not reach boat API."));
  }

  // ── Event Log ─────────────────────────────────────────────────────────────
  const logEntries = document.getElementById("log-entries");

  function logEvent(type, message) {
    const now = new Date().toLocaleTimeString("en-GB", { hour12: false });
    const el  = document.createElement("div");
    el.className   = `log-entry log-${type}`;
    el.textContent = `[${now}] ${message}`;
    logEntries.prepend(el);
    while (logEntries.children.length > 80) logEntries.removeChild(logEntries.lastChild);
  }

})();
