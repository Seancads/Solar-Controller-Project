// Devices page: list, add, edit, enable/disable, delete, API keys, simulator tools.

const gridEl = document.getElementById("device-grid");
const emptyEl = document.getElementById("device-empty");
const errorEl = document.getElementById("device-error");
const errorTextEl = document.getElementById("device-error-text");
const deviceDialog = document.getElementById("device-dialog");
const keyDialog = document.getElementById("key-dialog");
const form = {
  title: document.getElementById("device-dialog-title"),
  name: document.getElementById("f-name"),
  location: document.getElementById("f-location"),
  rated: document.getElementById("f-rated"),
  interval: document.getElementById("f-interval"),
  sim: document.getElementById("f-sim"),
  simRow: document.getElementById("f-sim-row"),
  error: document.getElementById("device-form-error"),
  save: document.getElementById("device-save"),
};

let devices = [];
let editingId = null;       // null = creating a new device
let keyDeviceId = null;

const STATUS = {
  online: ["dot-ok", "Online"],
  offline: ["dot-alert", "Offline"],
  never: ["dot-stale", "Never connected"],
  disabled: ["dot-stale", "Disabled"],
};

function signalText(rssi) {
  if (rssi === null || rssi === undefined) return "-";
  const quality = rssi >= -60 ? "excellent" : rssi >= -70 ? "good" : rssi >= -80 ? "fair" : "weak";
  return rssi + " dBm (" + quality + ")";
}

function lastSeenText(d) {
  if (!d.last_seen) return "never";
  const when = formatTimestamp(d.last_seen);
  return d.age_s === null ? when : formatDuration(d.age_s) + " ago (" + when + ")";
}

function metaRows(d) {
  const rows = [["Last data", lastSeenText(d)],
                ["Sends every", d.sample_interval_s + " s"],
                ["Panel rating", d.rated_watts + " W"]];
  if (d.simulated) {
    rows.push(["Source", "Built-in simulator"]);
  } else {
    rows.push(["Firmware", d.firmware || "-"], ["IP address", d.ip || "-"],
              ["Wi-Fi signal", signalText(d.rssi)],
              ["Uptime", d.uptime_s ? formatDuration(d.uptime_s) : "-"]);
  }
  return rows;
}

function miniStat(label, value, unit) {
  return el("div", { class: "mini" }, [
    el("div", { class: "mini-label", text: label }),
    el("div", { class: "mini-value", text: value === null ? "--" : value.toFixed(2) + " " + unit }),
  ]);
}

function button(label, onclick, extra) {
  return el("button", Object.assign({ class: "btn btn-sm", type: "button", text: label, onclick: onclick }, extra || {}));
}

function renderCard(d) {
  const status = STATUS[d.status] || STATUS.never;
  const r = d.reading;
  const actions = [button("Edit", () => openForm(d), { "data-focus": "edit-" + d.id })];
  if (!d.simulated) {
    actions.push(button("Connect / API key", () => openKeyDialog(d.id), { "data-focus": "key-" + d.id }));
  }
  actions.push(button(d.enabled ? "Disable" : "Enable", () => toggleEnabled(d), { "data-focus": "toggle-" + d.id }));
  actions.push(el("button", {
    class: "btn btn-sm btn-danger", type: "button", text: "Delete",
    "data-focus": "delete-" + d.id, onclick: () => removeDevice(d),
  }));

  const children = [
    el("div", { class: "device-head" }, [
      el("div", {}, [
        el("div", { class: "device-name" }, [el("span", { class: "dot " + status[0] }), el("span", { text: d.name })]),
        d.location ? el("div", { class: "device-loc", text: d.location }) : null,
      ]),
      el("div", { class: "btn-row" }, [
        d.simulated ? el("span", { class: "badge badge-sim", text: "Simulated" }) : null,
        el("span", { class: "badge " + (d.status === "online" ? "state-ok" : d.status === "offline" ? "state-bad" : ""), text: status[1] }),
      ]),
    ]),
    el("div", { class: "device-stats" }, [
      miniStat("Voltage", r ? r.voltage : null, "V"),
      miniStat("Current", r ? r.current : null, "A"),
      miniStat("Power", r ? r.power : null, "W"),
    ]),
    el("dl", { class: "device-meta" }, metaRows(d).reduce((acc, row) => {
      acc.push(el("dt", { text: row[0] }), el("dd", { text: row[1] }));
      return acc;
    }, [])),
    el("div", { class: "device-actions" }, actions),
  ];

  if (d.simulated && d.enabled) {
    children.push(el("div", { class: "sim-tools" }, [
      el("p", { class: "field-hint", text: "Test your alerts: make this simulated device misbehave for a short while." }),
      el("div", { class: "btn-row" }, [
        ["low_voltage", "Low voltage"], ["high_voltage", "High voltage"],
        ["high_current", "High current"], ["offline", "Go offline"],
      ].map((f) => button(f[1], () => simulateFault(d, f[0], f[1]), { "data-focus": "sim-" + f[0] + "-" + d.id }))),
    ]));
  }
  return el("article", { class: "device-card" + (d.enabled ? "" : " is-disabled") }, children);
}

function render() {
  // Rebuilding the cards would drop keyboard focus, so remember and restore it.
  const focused = document.activeElement && document.activeElement.getAttribute("data-focus");
  gridEl.textContent = "";
  devices.forEach((d) => gridEl.appendChild(renderCard(d)));
  emptyEl.classList.toggle("hidden", devices.length > 0);
  if (focused) {
    const again = gridEl.querySelector('[data-focus="' + focused + '"]');
    if (again) again.focus();
  }
}

async function refresh() {
  try {
    devices = await api("/api/devices");
    errorEl.classList.add("hidden");
    render();
  } catch (e) {
    errorTextEl.textContent = e.message;
    errorEl.classList.remove("hidden");
  }
}

// ---- add / edit ------------------------------------------------------------
function openForm(device) {
  editingId = device ? device.id : null;
  form.title.textContent = device ? "Edit device" : "Add device";
  form.name.value = device ? device.name : "";
  form.location.value = device ? device.location : "";
  form.rated.value = device ? device.rated_watts : 50;
  form.interval.value = device ? device.sample_interval_s : 5;
  form.sim.checked = false;
  form.simRow.classList.toggle("hidden", !!device);     // can't change after creation
  form.error.textContent = "";
  deviceDialog.showModal();
  form.name.focus();
}

form.sim.addEventListener("change", () => {
  if (editingId === null) form.interval.value = form.sim.checked ? 2 : 5;
});

document.getElementById("add-btn").addEventListener("click", () => openForm(null));
document.getElementById("device-cancel").addEventListener("click", () => deviceDialog.close());

document.getElementById("device-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = {
    name: form.name.value,
    location: form.location.value,
    rated_watts: form.rated.value,
    sample_interval_s: form.interval.value,
  };
  if (editingId === null) body.simulated = form.sim.checked;
  form.save.disabled = true;
  form.error.textContent = "";
  try {
    if (editingId === null) {
      const created = await api("/api/devices", { json: body });
      deviceDialog.close();
      await refresh();
      if (created.simulated) toast("Simulated device added.", "ok");
      else openKeyDialog(created.id);                   // straight to the ESP32 setup
    } else {
      await api("/api/devices/" + editingId, { method: "PATCH", json: body });
      deviceDialog.close();
      toast("Saved.", "ok");
      await refresh();
    }
  } catch (e) {
    form.error.textContent = e.message;
  } finally {
    form.save.disabled = false;
  }
});

// ---- enable / delete / simulate -----------------------------------------------
async function toggleEnabled(d) {
  try {
    await api("/api/devices/" + d.id, { method: "PATCH", json: { enabled: !d.enabled } });
    toast(d.name + (d.enabled ? " disabled." : " enabled."), "ok");
    refresh();
  } catch (e) { toast(e.message, "error"); }
}

async function removeDevice(d) {
  const ok = await confirmDialog(
    "Delete \"" + d.name + "\"? Its logged readings are deleted too. This can't be undone.", "Delete");
  if (!ok) return;
  try {
    await api("/api/devices/" + d.id, { method: "DELETE" });
    toast("Deleted.", "ok");
    refresh();
  } catch (e) { toast(e.message, "error"); }
}

async function simulateFault(d, fault, label) {
  try {
    const r = await api("/api/devices/" + d.id + "/simulate", { json: { fault: fault } });
    if (r.warning) toast(r.warning, "warning");
    else toast("Simulating " + r.label + " for " + r.seconds + " s. Watch the Alerts tab.", "ok");
  } catch (e) { toast(e.message, "error"); }
}

// ---- API key / ESP32 setup ----------------------------------------------------
function showKey(info) {
  document.getElementById("key-url").textContent = info.ingest_url;
  document.getElementById("key-value").textContent = info.api_key;
}

async function openKeyDialog(deviceId) {
  keyDeviceId = deviceId;
  const device = devices.find((d) => d.id === deviceId);
  document.getElementById("key-dialog-title").textContent = "Connect " + (device ? device.name : "your ESP32");
  document.getElementById("key-sketch").setAttribute("href", "/api/devices/" + deviceId + "/sketch");
  try {
    showKey(await api("/api/devices/" + deviceId + "/key"));
    keyDialog.showModal();
  } catch (e) { toast(e.message, "error"); }
}

document.getElementById("key-close").addEventListener("click", () => keyDialog.close());
keyDialog.querySelectorAll("[data-copy]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    await copyText(document.getElementById(btn.dataset.copy).textContent);
    const old = btn.textContent;
    btn.textContent = "Copied";
    setTimeout(() => { btn.textContent = old; }, 1500);
  });
});

document.getElementById("key-regen").addEventListener("click", async () => {
  const ok = await confirmDialog(
    "Make a new API key? The ESP32 using the old key stops working until you flash the new sketch.", "Make new key");
  if (!ok) return;
  try {
    showKey(await api("/api/devices/" + keyDeviceId + "/regenerate-key", { method: "POST" }));
    toast("New key created. Download the sketch again and re-flash the ESP32.", "warning");
  } catch (e) { toast(e.message, "error"); }
});

refresh();
setInterval(refresh, 3000);
