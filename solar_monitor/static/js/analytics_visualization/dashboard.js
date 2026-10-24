// Solar Monitor - live dashboard.
// Polls /api/live every 2 s for the selected device. Two different failures
// are kept apart on purpose:
//   * the SERVER can't be reached  -> "connection lost" popup
//   * the server is fine but the DEVICE stopped sending -> grey/amber status
//     plus a device-offline alert (raised by the server)

const statusEl = document.getElementById("status");
const statusLedEl = document.getElementById("status-led");
const alertBannerEl = document.getElementById("alert-banner");
const alertBannerTextEl = document.getElementById("alert-banner-text");
const deviceSelectEl = document.getElementById("device-select");
const noDeviceEl = document.getElementById("no-device");
const bodyEl = document.getElementById("dashboard-body");
const valueEls = {
  voltage: document.getElementById("voltage-value"),
  current: document.getElementById("current-value"),
  power: document.getElementById("power-value"),
};
const rangeEls = {
  voltage: document.getElementById("voltage-range"),
  current: document.getElementById("current-range"),
  power: document.getElementById("power-range"),
};
const peakPowerValueEl = document.getElementById("peak-power-value");
const energyValueEl = document.getElementById("energy-value");
const offlineModalEl = document.getElementById("offline-modal");
const offlineModalTextEl = document.getElementById("offline-modal-text");
const offlineModalDismissEl = document.getElementById("offline-modal-dismiss");
const rangeButtons = document.querySelectorAll(".range-btn");

const POLL_MS = 2000;
const FETCH_TIMEOUT_MS = 4000;   // give up on a single request after this long
const STALE_THRESHOLD_MS = 6000; // no successful reply for this long = server unreachable
const MAX_BUFFERED_POINTS = 600; // mirrors the server's history length

// ---- remembered device choice (storage can be blocked, so never rely on it)
function savedDeviceId() {
  try { return parseInt(localStorage.getItem("solar.device"), 10) || null; } catch (e) { return null; }
}
function saveDeviceId(id) {
  try { localStorage.setItem("solar.device", String(id)); } catch (e) { /* ignore */ }
}

// ---- "server unreachable" popup -------------------------------------------
// offlineModalDismissed is true while the user has closed the popup for the
// current outage; it resets on the next successful reply so a second outage
// shows the popup again.
let offlineModalDismissed = false;
offlineModalDismissEl.addEventListener("click", () => {
  offlineModalDismissed = true;
  offlineModalEl.classList.add("hidden");
});

// ---- chart ----------------------------------------------------------------
const chart = new Chart(document.getElementById("mainChart").getContext("2d"), {
  type: "line",
  data: {
    labels: [],
    datasets: [
      { label: "Voltage (V)", data: [], borderColor: "#f5b942", tension: 0.3, pointRadius: 0, borderWidth: 2 },
      { label: "Current (A)", data: [], borderColor: "#a78bfa", tension: 0.3, pointRadius: 0, borderWidth: 2 },
      { label: "Power (W)", data: [], borderColor: "#4fd6c8", tension: 0.3, pointRadius: 0, borderWidth: 2 },
    ],
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    scales: {
      x: { ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8, font: { size: 10 } }, grid: { color: "#2a2a38" }, border: { display: false } },
      y: { beginAtZero: true, ticks: { font: { size: 10 } }, grid: { color: "#2a2a38" }, border: { display: false } },
    },
    plugins: {
      legend: { labels: { color: "#f1f1f5", font: { size: 11 }, boxWidth: 12, usePointStyle: true, pointStyle: "circle" } },
    },
  },
});

// Every reading we hold, independent of the chart; the chart shows a slice.
let allReadings = [];
let selectedSeconds = 60;       // number of seconds, or "all"
let sampleInterval = 2;         // seconds between a device's readings

rangeButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    const val = btn.dataset.seconds;
    selectedSeconds = val === "all" ? "all" : parseInt(val, 10);
    rangeButtons.forEach((b) => b.classList.toggle("active", b === btn));
    renderChart();
  });
});
rangeButtons[0].classList.add("active");

function renderChart() {
  let slice = allReadings;
  if (selectedSeconds !== "all") {
    // Readings arrive every `sampleInterval` seconds, so a time window is a
    // number of points.
    slice = allReadings.slice(-Math.max(2, Math.ceil(selectedSeconds / sampleInterval)));
  }
  chart.data.labels = slice.map((r) => r.timestamp);
  chart.data.datasets[0].data = slice.map((r) => r.voltage);
  chart.data.datasets[1].data = slice.map((r) => r.current);
  chart.data.datasets[2].data = slice.map((r) => r.power);
  chart.update();
}

function addReading(reading) {
  const last = allReadings[allReadings.length - 1];
  if (last && last.ts === reading.ts) return false;   // already have it (device is slower than our polling)
  allReadings.push(reading);
  if (allReadings.length > MAX_BUFFERED_POINTS) allReadings.shift();
  return true;
}

// ---- devices ----------------------------------------------------------------
let devices = [];
let currentDeviceId = null;

async function loadDevices() {
  devices = await api("/api/devices");
  deviceSelectEl.textContent = "";
  devices.forEach((d) => {
    deviceSelectEl.appendChild(el("option", { value: d.id, text: d.name + (d.enabled ? "" : " (disabled)") }));
  });
  const hasDevices = devices.length > 0;
  noDeviceEl.classList.toggle("hidden", hasDevices);
  bodyEl.classList.toggle("hidden", !hasDevices);
  deviceSelectEl.classList.toggle("hidden", !hasDevices);
  if (!hasDevices) {
    currentDeviceId = null;
    setStatus("dot-stale", "no devices");
    return;
  }
  const wanted = [savedDeviceId(), currentDeviceId].find((id) => devices.some((d) => d.id === id));
  const fallback = (devices.find((d) => d.enabled) || devices[0]).id;
  await switchDevice(wanted || fallback);
}

async function switchDevice(id) {
  currentDeviceId = id;
  saveDeviceId(id);
  deviceSelectEl.value = String(id);
  allReadings = [];
  lastSuccessTime = null;
  clearCards();
  renderChart();
  await loadHistory();
  fetchLive();
}

deviceSelectEl.addEventListener("change", () => switchDevice(parseInt(deviceSelectEl.value, 10)));

// ---- cards ----------------------------------------------------------------
function clearCards() {
  Object.keys(valueEls).forEach((k) => {
    valueEls[k].textContent = "--";
    rangeEls[k].textContent = "today --";
  });
  peakPowerValueEl.textContent = "--";
  energyValueEl.textContent = "--";
}

function setStatus(dotClass, text) {
  statusLedEl.className = "dot " + dotClass;
  statusEl.textContent = text;
}

function renderBanner(list) {
  if (!list.length) {
    alertBannerEl.classList.add("hidden");
    return;
  }
  const extra = list.length > 1 ? " (+" + (list.length - 1) + " more)" : "";
  alertBannerTextEl.textContent = list[0].message + extra;
  const critical = list.some((a) => a.severity === "critical");
  alertBannerEl.classList.toggle("warn", !critical);
  alertBannerEl.classList.remove("hidden");
}

function applyLive(p) {
  sampleInterval = p.device.sample_interval_s || 2;
  const r = p.reading;

  if (r) {
    Object.keys(valueEls).forEach((k) => { valueEls[k].textContent = r[k].toFixed(2); });
    peakPowerValueEl.textContent = p.peak_power.toFixed(2);
    energyValueEl.textContent = p.energy_wh.toFixed(3) + " Wh";
    Object.keys(rangeEls).forEach((k) => {
      const range = p.ranges[k];
      rangeEls[k].textContent = range.min === null
        ? "today --"
        : "today " + range.min.toFixed(2) + " – " + range.max.toFixed(2);
    });
    if (addReading(r)) renderChart();
  }

  // What the status pill says depends on the DEVICE, not on the server.
  if (p.status === "online" && r) setStatus("dot-ok", "live — " + r.timestamp);
  else if (p.status === "offline") {
    setStatus("dot-warn", "device offline — " + (r ? "last data " + r.timestamp : formatDuration(p.age_s) + " ago"));
  } else if (p.status === "disabled") setStatus("dot-stale", "device disabled");
  else setStatus("dot-stale", "waiting for first data");

  renderBanner(p.alerts);
}

// ---- polling --------------------------------------------------------------
let lastSuccessTime = null;
let lastKnownTimestamp = null;
// Guards against out-of-order replies: a slow request that finishes after a
// newer one must not overwrite the newer, correct state.
let requestSeq = 0;
let isFetching = false;

async function fetchLive() {
  if (isFetching || currentDeviceId === null) return;
  isFetching = true;
  const mySeq = ++requestSeq;
  const deviceId = currentDeviceId;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

  try {
    const res = await fetch("/api/live?device=" + deviceId, { signal: controller.signal });
    clearTimeout(timeoutId);
    if (mySeq !== requestSeq || deviceId !== currentDeviceId) return;

    lastSuccessTime = Date.now();       // the server answered, whatever it said
    offlineModalEl.classList.add("hidden");
    offlineModalDismissed = false;

    if (res.status === 404) {           // that device was deleted elsewhere
      isFetching = false;
      await loadDevices();
      return;
    }
    if (!res.ok) throw new Error("Bad response");
    const payload = await res.json();
    if (payload.reading) lastKnownTimestamp = payload.reading.timestamp;
    applyLive(payload);
  } catch (err) {
    clearTimeout(timeoutId);
    if (mySeq !== requestSeq) return;
    markServerUnreachable();
    console.error(err);
  } finally {
    isFetching = false;
  }
}

function markServerUnreachable() {
  setStatus("dot-stale", lastKnownTimestamp
    ? "server unreachable — last update " + lastKnownTimestamp
    : "server unreachable");
  if (!offlineModalDismissed) {
    offlineModalTextEl.textContent = lastKnownTimestamp
      ? "The dashboard hasn't heard from the server since " + lastKnownTimestamp + "."
      : "The dashboard can't reach the server.";
    offlineModalEl.classList.remove("hidden");
  }
}

// Independent of fetchLive, so a request that hangs forever still gets noticed.
function checkForStaleConnection() {
  if (lastSuccessTime !== null && Date.now() - lastSuccessTime > STALE_THRESHOLD_MS) {
    markServerUnreachable();
  }
}

async function loadHistory() {
  if (currentDeviceId === null) return;
  const deviceId = currentDeviceId;
  try {
    const readings = await api("/api/history?device=" + deviceId);
    if (deviceId !== currentDeviceId) return;      // user switched meanwhile
    allReadings = readings.slice(-MAX_BUFFERED_POINTS);
    renderChart();
  } catch (err) {
    console.error("Could not load history", err);
  }
}

// Browsers throttle timers in background tabs; catch up as soon as it's visible.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") fetchLive();
});

// One timer drives everything. Until a device is chosen it keeps retrying the
// device list, so the page recovers on its own if the server was down at load
// time, and picks up a device that gets added from another tab.
async function tick() {
  if (currentDeviceId !== null) return fetchLive();
  try {
    await loadDevices();
    offlineModalEl.classList.add("hidden");
    offlineModalDismissed = false;
  } catch (err) {
    markServerUnreachable();
  }
}

tick();
setInterval(tick, POLL_MS);
setInterval(checkForStaleConnection, 1000);
