// Solar Power Monitoring - Analytics page logic
// Colour meaning on this page: purple = energy, cyan = power, amber =
// warning / below normal. Energy and power use the same colours as the
// matching cards on the live dashboard.

const totalEnergyEl = document.getElementById("total-energy-value");
const totalEnergySubEl = document.getElementById("total-energy-sub");
const avgEnergyEl = document.getElementById("avg-energy-value");
const bestDayValueEl = document.getElementById("best-day-value");
const bestDayDateEl = document.getElementById("best-day-date");
const avgEfficiencyEl = document.getElementById("avg-efficiency-value");
const lowDaysNoteEl = document.getElementById("low-days-note");
const hourlySubEl = document.getElementById("hourly-sub");
const compareRowsEl = document.getElementById("compare-rows");
const rateInputEl = document.getElementById("rate-input");
const savingsLabelEl = document.getElementById("savings-label");
const savingsValueEl = document.getElementById("savings-value");
const co2ValueEl = document.getElementById("co2-value");
const rangeButtons = document.querySelectorAll(".range-btn[data-days]");
const sourceButtons = document.querySelectorAll(".range-btn[data-source]");
const deviceSelectEl = document.getElementById("a-device");
const sourceNoteEl = document.getElementById("source-note");
const emptyEl = document.getElementById("a-empty");
const bodyEl = document.getElementById("a-body");

// A day is "underperforming" if its energy is below this fraction of
// the average for the selected range.
const LOW_DAY_THRESHOLD = 0.75;
// Rough grid emissions factor - an assumption, not a measurement.
const CO2_KG_PER_KWH = 0.5;

const COLOR_ENERGY = "#8b5cf6";
const COLOR_POWER = "#4fd6c8";
const COLOR_WARN = "#f5b942";

let currentTotalKwh = 0;
let currentDayCount = 30;
let currentNumDays = 30;
let source = "simulated";        // "simulated" or "logged"
let currentPartial = [];         // per-bar: true for today's unfinished day

// Query string for the chosen data source (and device, for logged data).
function sourceQuery() {
  return "&source=" + source + (source === "logged" && deviceSelectEl.value ? "&device=" + deviceSelectEl.value : "");
}

function formatDateLabel(isoDate) {
  const d = new Date(isoDate + "T00:00:00");
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function formatDateLong(isoDate) {
  const d = new Date(isoDate + "T00:00:00");
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

function formatHour(h) {
  return (h % 12 === 0 ? 12 : h % 12) + " " + (h < 12 ? "AM" : "PM");
}

function mean(values) {
  return values.reduce((a, b) => a + b, 0) / values.length;
}

// Few, horizontal labels read far better than 30 rotated ones.
// Fewer labels on phones, where 8 across ~340px collide.
const maxXTicks = window.innerWidth < 480 ? 5 : 8;
const dateTicks = { maxRotation: 0, autoSkip: true, maxTicksLimit: maxXTicks };
// ~5 gridlines is plenty on the short charts.
const yTicks = { maxTicksLimit: 6 };

// Single-series charts don't need the colour swatch in the tooltip.
function singleSeriesTooltip(unit, decimals, titles) {
  return {
    displayColors: false,
    callbacks: {
      title: titles,
      label: (ctx) => ctx.parsed.y.toFixed(decimals) + " " + unit,
    },
  };
}

// Keep the raw ISO dates so tooltips can show a full "Mon, Sep 28".
let currentDates = [];
const dateTitle = (items) => formatDateLong(currentDates[items[0].dataIndex]) +
  (currentPartial[items[0].dataIndex] ? " (so far)" : "");

const energyChart = new Chart(document.getElementById("energyChart").getContext("2d"), {
  type: "bar",
  data: {
    labels: [],
    datasets: [{
      label: "Energy",
      data: [],
      backgroundColor: COLOR_ENERGY,
      borderRadius: 5,
      maxBarThickness: 34, // stops the 7-day view turning into huge slabs
    }],
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    scales: {
      x: { ticks: dateTicks, grid: { display: false }, border: { display: false } },
      y: { beginAtZero: true, ticks: yTicks, border: { display: false } },
    },
    plugins: {
      legend: { display: false },
      tooltip: singleSeriesTooltip("Wh", 0, dateTitle),
    },
  },
});

const peakChart = new Chart(document.getElementById("peakChart").getContext("2d"), {
  type: "line",
  data: {
    labels: [],
    datasets: [{
      label: "Peak power",
      data: [],
      borderColor: COLOR_POWER,
      backgroundColor: "rgba(79, 214, 200, 0.10)",
      fill: true,
      // Days are separate measurements, not a continuous signal, so no
      // curve smoothing: it would invent dips and bumps between days.
      tension: 0,
      pointRadius: 3,
      pointHoverRadius: 5,
      pointBackgroundColor: COLOR_POWER,
      borderWidth: 2,
    }],
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    scales: {
      x: { ticks: dateTicks, grid: { display: false }, border: { display: false } },
      // Start at zero so a 45W -> 25W dip looks like the ~45% drop it is.
      y: { beginAtZero: true, ticks: yTicks, border: { display: false } },
    },
    plugins: {
      legend: { display: false },
      tooltip: singleSeriesTooltip("W", 1, dateTitle),
    },
  },
});

const hourlyChart = new Chart(document.getElementById("hourlyChart").getContext("2d"), {
  type: "line",
  data: {
    labels: [],
    datasets: [{
      label: "Average power",
      data: [],
      borderColor: COLOR_POWER,
      backgroundColor: "rgba(79, 214, 200, 0.14)",
      fill: true,
      tension: 0.4, // smoothing is fair here: power really is continuous
      pointRadius: 0,
      pointHoverRadius: 5,
      borderWidth: 2,
    }],
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    scales: {
      x: {
        // Label round hours only (every 3h, or 6h on phones) instead of
        // whatever step autoSkip happens to pick.
        ticks: {
          maxRotation: 0,
          autoSkip: false,
          callback: function (value, index) {
            return index % (window.innerWidth < 480 ? 6 : 3) === 0 ? this.getLabelForValue(value) : "";
          },
        },
        grid: { display: false },
        border: { display: false },
      },
      y: { beginAtZero: true, ticks: yTicks, border: { display: false } },
    },
    plugins: {
      legend: { display: false },
      tooltip: singleSeriesTooltip("W", 1),
    },
  },
});

// "Complete" days exclude today's unfinished day, which would otherwise look
// like a terrible day and drag every average down. If there is nothing else
// (a brand-new install), fall back to using what exists.
function completeDays(days) {
  const full = days.filter((d) => !d.partial);
  return full.length ? full : days;
}

function renderStats(days) {
  const full = completeDays(days);
  const totalEnergy = days.reduce((sum, d) => sum + d.total_energy_wh, 0);
  const avgEnergy = mean(full.map((d) => d.total_energy_wh));
  const avgEfficiency = mean(full.map((d) => d.efficiency_pct));
  const bestDay = full.reduce((best, d) => (d.total_energy_wh > best.total_energy_wh ? d : best), full[0]);

  totalEnergyEl.textContent = (totalEnergy / 1000).toFixed(2) + " kWh";
  totalEnergySubEl.textContent = "last " + days.length + (days.length === 1 ? " day" : " days");
  avgEnergyEl.textContent = avgEnergy.toFixed(0) + " Wh";
  bestDayValueEl.textContent = bestDay.total_energy_wh.toFixed(0) + " Wh";
  bestDayDateEl.textContent = formatDateLabel(bestDay.date);
  avgEfficiencyEl.textContent = avgEfficiency.toFixed(1) + "%";

  currentTotalKwh = totalEnergy / 1000;
  currentDayCount = days.length;
  renderSavings();
}

function renderEnergyChart(days) {
  const full = completeDays(days);
  const cutoff = mean(full.map((d) => d.total_energy_wh)) * LOW_DAY_THRESHOLD;
  // An unfinished day is never flagged as underperforming.
  const isLow = days.map((d) => !d.partial && d.total_energy_wh < cutoff);

  currentDates = days.map((d) => d.date);
  currentPartial = days.map((d) => !!d.partial);
  energyChart.data.labels = days.map((d) => formatDateLabel(d.date));
  energyChart.data.datasets[0].data = days.map((d) => d.total_energy_wh);
  energyChart.data.datasets[0].backgroundColor = isLow.map((low) => (low ? COLOR_WARN : COLOR_ENERGY));
  energyChart.update();

  const lowCount = isLow.filter(Boolean).length;
  const pct = Math.round(LOW_DAY_THRESHOLD * 100);
  lowDaysNoteEl.textContent = "";
  if (lowCount === 0) {
    lowDaysNoteEl.textContent = "No underperforming days in this range.";
  } else {
    const swatch = document.createElement("span");
    swatch.className = "note-swatch";
    lowDaysNoteEl.append(
      swatch,
      lowCount + (lowCount === 1 ? " day is" : " days are") + " below " + pct + "% of the average."
    );
  }
  if (days.some((d) => d.partial)) {
    lowDaysNoteEl.append(" Today is still in progress, so it isn't counted in averages.");
  }
}

function renderPeakChart(days) {
  peakChart.data.labels = days.map((d) => formatDateLabel(d.date));
  peakChart.data.datasets[0].data = days.map((d) => d.peak_power_w);
  peakChart.update();
}

function renderHourly(hourly) {
  const peak = hourly.reduce((best, p) => (p.avg_power_w > best.avg_power_w ? p : best), hourly[0]);
  hourlyChart.data.labels = hourly.map((p) => formatHour(p.hour));
  hourlyChart.data.datasets[0].data = hourly.map((p) => p.avg_power_w);
  // Mark the peak hour with a dot (only if there is any output at all).
  hourlyChart.data.datasets[0].pointRadius = hourly.map((p) => (p === peak && peak.avg_power_w > 0 ? 5 : 0));
  hourlyChart.data.datasets[0].pointBackgroundColor = COLOR_POWER;
  hourlyChart.update();
  hourlySubEl.textContent = peak.avg_power_w > 0
    ? "Peaks around " + formatHour(peak.hour) + " at " + peak.avg_power_w.toFixed(0) + " W"
    : "No output recorded in this range";
}

function renderSavings() {
  const rate = parseFloat(rateInputEl.value);
  const validRate = Number.isFinite(rate) && rate >= 0;
  savingsLabelEl.textContent = "Savings, " + currentDayCount + (currentDayCount === 1 ? " day" : " days");
  savingsValueEl.textContent = validRate ? (currentTotalKwh * rate).toFixed(2) : "--";
  co2ValueEl.textContent = (currentTotalKwh * CO2_KG_PER_KWH).toFixed(1) + " kg";
}

function percentChange(current, previous) {
  return previous === 0 ? 0 : ((current - previous) / previous) * 100;
}

function renderComparison(all) {
  const last14 = all.filter((d) => !d.partial).slice(-14);
  compareRowsEl.textContent = "";
  if (last14.length < 14) {
    compareRowsEl.appendChild(el("div", { class: "empty", style: "padding:14px 0",
      text: "Needs 14 full days of data. " + last14.length + " so far." }));
    return;
  }
  const previous = last14.slice(0, 7);
  const recent = last14.slice(7);

  const metrics = [
    { name: "Energy", fmt: (v) => v.toFixed(0) + " Wh", get: (set) => set.reduce((s, d) => s + d.total_energy_wh, 0) },
    { name: "Avg peak power", fmt: (v) => v.toFixed(1) + " W", get: (set) => mean(set.map((d) => d.peak_power_w)) },
    { name: "Avg efficiency", fmt: (v) => v.toFixed(1) + "%", get: (set) => mean(set.map((d) => d.efficiency_pct)) },
  ];

  metrics.forEach((m) => {
    const cur = m.get(recent);
    const prev = m.get(previous);
    const change = percentChange(cur, prev);
    const up = change >= 0;
    compareRowsEl.appendChild(el("div", { class: "compare-row" }, [
      el("div", { class: "compare-name-block" }, [
        el("span", { class: "compare-name", text: m.name }),
        el("span", { class: "compare-prev", text: "before: " + m.fmt(prev) }),
      ]),
      // Arrow + sign as well as colour, so it doesn't rely on colour alone.
      el("span", {}, [
        el("span", { class: "compare-value", text: m.fmt(cur) }),
        el("span", { class: "delta " + (up ? "delta-up" : "delta-down"), text: (up ? "▲ +" : "▼ ") + change.toFixed(1) + "%" }),
      ]),
    ]));
  });
}

function setNote() {
  if (source === "simulated") {
    sourceNoteEl.textContent = "Simulated data for the last 30 days. Switch to Logged to see what your devices have really recorded.";
  } else {
    const name = deviceSelectEl.options[deviceSelectEl.selectedIndex];
    sourceNoteEl.textContent = "Real readings logged by " + (name ? name.textContent : "your device") +
      ". The most recent day is partial until midnight.";
  }
}

function showEmpty(message) {
  emptyEl.textContent = message;
  emptyEl.classList.remove("hidden");
  bodyEl.classList.add("hidden");
}

// Guards against a slow reply from a previous selection overwriting a newer one.
let loadSeq = 0;

async function loadAnalytics() {
  const seq = ++loadSeq;
  setNote();
  try {
    const q = "days=" + currentNumDays + sourceQuery();
    const [days, hourly, last14] = await Promise.all([
      api("/api/analytics?" + q),
      api("/api/analytics/hourly?" + q),
      api("/api/analytics?days=14" + sourceQuery()),
    ]);
    if (seq !== loadSeq) return;
    if (!days.length) {
      showEmpty("Nothing has been logged for this device yet. Readings are saved while it sends data, " +
        "and the first day appears here straight away.");
      return;
    }
    emptyEl.classList.add("hidden");
    bodyEl.classList.remove("hidden");
    renderStats(days);
    renderEnergyChart(days);
    renderPeakChart(days);
    renderHourly(hourly);
    renderComparison(last14);
  } catch (err) {
    if (seq === loadSeq) showEmpty(err.message);
  }
}

rangeButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    rangeButtons.forEach((b) => b.classList.toggle("active", b === btn));
    currentNumDays = parseInt(btn.dataset.days, 10);
    loadAnalytics();
  });
});

function setSource(next) {
  source = next;
  sourceButtons.forEach((b) => b.classList.toggle("active", b.dataset.source === next));
  deviceSelectEl.classList.toggle("hidden", next !== "logged");
  loadAnalytics();
}
sourceButtons.forEach((btn) => btn.addEventListener("click", () => setSource(btn.dataset.source)));
deviceSelectEl.addEventListener("change", loadAnalytics);
rateInputEl.addEventListener("input", renderSavings);

(async function init() {
  document.querySelector('.range-btn[data-days="30"]').classList.add("active");
  try {
    const devices = await api("/api/devices");
    devices.forEach((d) => deviceSelectEl.appendChild(el("option", { value: d.id, text: d.name })));
  } catch (e) { /* the page still works on simulated data */ }
  setSource("simulated");
})();
