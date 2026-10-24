// Reports page: summary, chart, table, exports, saved reports, logging settings.

const $ = (id) => document.getElementById(id);
const deviceEl = $("r-device"), rangeEl = $("r-range"), fromEl = $("r-from"), toEl = $("r-to");
const errorEl = $("r-error");

const narrow = window.innerWidth < 480;
const chart = new Chart($("reportChart").getContext("2d"), {
  type: "line",
  data: {
    labels: [],
    datasets: [
      { label: "Average power", data: [], borderColor: "#4fd6c8", backgroundColor: "rgba(79, 214, 200, 0.12)",
        fill: true, tension: 0, pointRadius: 0, pointHoverRadius: 4, borderWidth: 2 },
      { label: "Peak power", data: [], borderColor: "#a78bfa", borderDash: [5, 4],
        fill: false, tension: 0, pointRadius: 0, pointHoverRadius: 4, borderWidth: 1.5 },
    ],
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    scales: {
      x: { ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: narrow ? 3 : 6, font: { size: 10 } }, grid: { display: false }, border: { display: false } },
      y: { beginAtZero: true, ticks: { maxTicksLimit: 6, font: { size: 10 } }, grid: { color: "#2a2a38" }, border: { display: false } },
    },
    plugins: {
      legend: { labels: { color: "#f1f1f5", font: { size: 11 }, boxWidth: 12, usePointStyle: true, pointStyle: "circle" } },
      tooltip: { callbacks: { label: (ctx) => ctx.dataset.label + ": " + ctx.parsed.y.toFixed(1) + " W" } },
    },
  },
});

function todayText(offsetDays) {
  const d = new Date(Date.now() - (offsetDays || 0) * 86400000);
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
}

function query() {
  const p = new URLSearchParams({ device: deviceEl.value, range: rangeEl.value });
  if (rangeEl.value === "custom") { p.set("from", fromEl.value); p.set("to", toEl.value); }
  return p.toString();
}

rangeEl.addEventListener("change", () => $("r-custom").classList.toggle("hidden", rangeEl.value !== "custom"));
fromEl.value = todayText(7);
toEl.value = todayText(0);
fromEl.max = toEl.max = todayText(0);

function num(value, digits, unit) {
  return value === null || value === undefined ? "--" : value.toFixed(digits) + (unit ? " " + unit : "");
}

function renderReport(r) {
  const s = r.summary;
  $("s-energy").textContent = formatEnergy(s.energy_wh);
  $("s-label").textContent = r.label;
  $("s-avg").textContent = num(s.avg_p, 1, "W");
  $("s-peak").textContent = num(s.peak_p, 1, "W");
  $("s-volt").textContent = num(s.avg_v, 2, "V");
  $("s-volt-range").textContent = s.min_v === null ? "--" : num(s.min_v, 1) + " – " + num(s.max_v, 1) + " V";
  $("s-count").textContent = s.n.toLocaleString();
  $("s-first").textContent = "since " + formatTimestamp(s.first_ts);
  $("chart-sub").textContent = "Average and peak for each " + r.bucket_name;

  chart.data.labels = r.table.map((b) => b.label);
  chart.data.datasets[0].data = r.table.map((b) => b.avg_power);
  chart.data.datasets[1].data = r.table.map((b) => b.peak_power);
  chart.update();

  const body = $("r-table");
  body.textContent = "";
  r.table.forEach((b) => {
    body.appendChild(el("tr", {}, [
      el("td", { class: "nowrap", text: b.label }),
      el("td", { class: "num", text: b.avg_voltage.toFixed(2) }),
      el("td", { class: "num", text: b.avg_current.toFixed(2) }),
      el("td", { class: "num", text: b.avg_power.toFixed(1) }),
      el("td", { class: "num", text: b.peak_power.toFixed(1) }),
      el("td", { class: "num", text: b.energy_wh.toFixed(2) }),
      el("td", { class: "num", text: String(b.samples) }),
    ]));
  });

  const q = query();
  $("x-summary").href = "/api/reports/export.csv?" + q + "&kind=summary";
  $("x-raw").href = "/api/reports/export.csv?" + q + "&kind=raw";
  $("x-print").href = "/reports/print?" + q;
}

async function showReport() {
  errorEl.textContent = "";
  if (!deviceEl.value) return;
  $("r-apply").disabled = true;
  try {
    const r = await api("/api/reports/summary?" + query());
    const empty = r.summary.n === 0;
    $("r-body").classList.toggle("hidden", empty);
    $("r-empty").classList.toggle("hidden", !empty);
    if (empty) {
      $("r-empty").textContent = "No readings were logged for " + r.label.toLowerCase() +
        ". Readings are logged while a device is sending data.";
    } else {
      renderReport(r);
    }
  } catch (e) {
    errorEl.textContent = e.message;
    $("r-body").classList.add("hidden");
    $("r-empty").classList.add("hidden");
  } finally {
    $("r-apply").disabled = false;
  }
}

$("r-apply").addEventListener("click", showReport);

$("x-save").addEventListener("click", async () => {
  const body = { device: parseInt(deviceEl.value, 10), range: rangeEl.value };
  if (rangeEl.value === "custom") { body.from = fromEl.value; body.to = toEl.value; }
  try {
    await api("/api/reports/generate", { json: body });
    toast("Report saved. You'll find it under Saved reports below.", "ok");
    loadSaved();
  } catch (e) { toast(e.message, "error"); }
});

// ---- saved reports -----------------------------------------------------------
async function loadSaved() {
  const list = $("saved-list");
  try {
    const files = await api("/api/reports/saved");
    list.textContent = "";
    if (!files.length) {
      list.appendChild(el("div", { class: "empty", text: "No saved reports yet." }));
      return;
    }
    files.forEach((f) => {
      list.appendChild(el("div", { class: "file-row" }, [
        el("div", {}, [
          el("div", { class: "file-name", text: f.name }),
          el("div", { class: "file-meta", text: (f.kind === "daily" ? "Daily report" : "Saved report") + " · " +
            f.format.toUpperCase() + " · " + formatBytes(f.size) + " · " + formatTimestamp(f.mtime) }),
        ]),
        el("a", { class: "btn btn-sm", href: "/reports/files/" + encodeURIComponent(f.name),
                  target: f.format === "html" ? "_blank" : null, rel: "noopener",
                  text: f.format === "html" ? "Open" : "Download" }),
      ]));
    });
  } catch (e) { /* ignore */ }
}

// ---- logging settings --------------------------------------------------------
async function loadSettings() {
  const s = await api("/api/settings/logging");
  $("l-interval").value = s.log_interval_s;
  $("l-retention").value = s.retention_days;
  $("l-info").textContent = s.rows.toLocaleString() + " readings stored (" + formatBytes(s.db_bytes) + ")" +
    (s.oldest_ts ? ", the oldest from " + formatTimestamp(s.oldest_ts) + "." : ".");
}

$("l-save").addEventListener("click", async () => {
  $("l-error").textContent = "";
  try {
    await api("/api/settings/logging", { method: "PUT", json: {
      log_interval_s: $("l-interval").value, retention_days: $("l-retention").value } });
    toast("Logging settings saved.", "ok");
    loadSettings();
  } catch (e) { $("l-error").textContent = e.message; }
});

// ---- start ---------------------------------------------------------------------
(async function init() {
  try {
    const devices = await api("/api/devices");
    devices.forEach((d) => deviceEl.appendChild(el("option", { value: d.id, text: d.name })));
    if (!devices.length) {
      $("r-empty").textContent = "No devices yet. Add one on the Devices page.";
      $("r-empty").classList.remove("hidden");
    } else {
      showReport();
    }
    await loadSettings();
  } catch (e) {
    errorEl.textContent = e.message;
  }
  loadSaved();
})();
