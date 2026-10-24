// Alerts page: alert list + history, rule editor, notification settings.

const TABS = ["alerts", "rules", "notifications"];
const tabButtons = document.querySelectorAll("[data-tab]");
const loaded = {};                       // which tabs have been loaded once

const SEVERITY_LABEL = { info: "Info", warning: "Warning", critical: "Critical" };
const STATE_LABEL = { active: "Active", acknowledged: "Acknowledged", resolved: "Resolved" };
const CHANNEL_LABEL = { webhook: "Webhook", telegram: "Telegram", email: "Email", all: "All channels" };

function cell(content, cls) {
  return el("td", { class: cls }, [content]);
}

// ================================================================== alerts tab
const activeListEl = document.getElementById("active-list");
const historyBodyEl = document.getElementById("history-body");
const historyEmptyEl = document.getElementById("history-empty");
const ackAllEl = document.getElementById("ack-all");

function severityBadge(sev) {
  return el("span", { class: "badge sev-" + sev, text: SEVERITY_LABEL[sev] || sev });
}

function renderActive(list) {
  activeListEl.textContent = "";
  if (!list.length) {
    activeListEl.appendChild(el("div", { class: "empty", text: "No active alerts. Everything is running normally." }));
  }
  list.forEach((a) => {
    const meta = "Started " + formatTimestamp(a.started_at) + " · open for " + formatDuration(a.duration_s) +
      (a.notified ? " · notification sent" : "");
    activeListEl.appendChild(el("div", { class: "alert-item sev-" + a.severity + (a.state === "acknowledged" ? " is-acked" : "") }, [
      el("div", { class: "alert-body" }, [
        el("div", { class: "alert-msg", text: a.message }),
        el("div", { class: "alert-meta", text: meta }),
      ]),
      severityBadge(a.severity),
      a.state === "active"
        ? el("button", { class: "btn btn-sm", type: "button", text: "Acknowledge", onclick: () => acknowledge(a.id) })
        : el("span", { class: "badge", text: "Acknowledged" }),
    ]));
  });
  ackAllEl.classList.toggle("hidden", !list.some((a) => a.state === "active"));
}

function renderHistory(list) {
  historyBodyEl.textContent = "";
  historyEmptyEl.classList.toggle("hidden", list.length > 0);
  list.forEach((a) => {
    historyBodyEl.appendChild(el("tr", {}, [
      cell(formatTimestamp(a.started_at), "nowrap"),
      cell(severityBadge(a.severity)),
      cell(a.device_name, "nowrap"),
      cell(a.message),
      cell(formatDuration(a.duration_s) + (a.state === "resolved" ? "" : " so far"), "nowrap"),
      cell(el("span", { class: "badge" + (a.state === "resolved" ? " state-resolved" : a.state === "active" ? " state-bad" : ""),
                         text: STATE_LABEL[a.state] }), "nowrap"),
    ]));
  });
}

async function loadAlerts() {
  try {
    const [active, all] = await Promise.all([api("/api/alerts?status=active"), api("/api/alerts?limit=50")]);
    renderActive(active);
    renderHistory(all);
  } catch (e) { /* the nav badge/dashboard already report server trouble */ }
}

async function acknowledge(id) {
  try {
    await api("/api/alerts/" + id + "/ack", { method: "POST" });
    loadAlerts();
  } catch (e) { toast(e.message, "error"); loadAlerts(); }
}

ackAllEl.addEventListener("click", async () => {
  try { await api("/api/alerts/ack-all", { method: "POST" }); loadAlerts(); }
  catch (e) { toast(e.message, "error"); }
});

// ================================================================== rules tab
const rulesListEl = document.getElementById("rules-list");
const rulesErrorEl = document.getElementById("rules-error");
let ruleForms = [];

const RULE_LABELS = {
  low_voltage: "Alert when below",
  high_voltage: "Alert when above",
  high_current: "Alert when above",
  device_offline: "Alert when no data for more than",
};

function field(label, input) {
  return el("div", {}, [el("label", { class: "field-label", text: label }), input]);
}

function renderRules(rules) {
  rulesListEl.textContent = "";
  ruleForms = rules.map((rule) => {
    const enabled = el("input", { type: "checkbox" });
    enabled.checked = rule.enabled;
    const threshold = el("input", { class: "field-input", type: "number", step: "any", min: "0", value: rule.threshold });
    const severity = el("select", { class: "field-input select" },
      ["info", "warning", "critical"].map((s) => el("option", { value: s, text: SEVERITY_LABEL[s] })));
    severity.value = rule.severity;
    const confirmN = el("input", { class: "field-input", type: "number", min: "1", max: "20", step: "1", value: rule.confirm_n });

    const fields = [
      field(RULE_LABELS[rule.type], el("div", { class: "input-unit" }, [threshold, el("span", { text: rule.unit })])),
      field("Severity", severity),
    ];
    if (rule.type !== "device_offline") fields.push(field("Confirm after (readings in a row)", confirmN));

    let hoursOn = null, from = null, to = null;
    if (rule.type === "low_voltage") {
      hoursOn = el("input", { type: "checkbox" });
      from = el("input", { class: "field-input", type: "time", value: rule.active_from || "07:00" });
      to = el("input", { class: "field-input", type: "time", value: rule.active_to || "17:00" });
      hoursOn.checked = !!(rule.active_from && rule.active_to);
      const hoursFields = el("div", { class: "rule-fields", style: "margin-top:10px" }, [field("From", from), field("Until", to)]);
      const sync = () => hoursFields.classList.toggle("hidden", !hoursOn.checked);
      hoursOn.addEventListener("change", sync);
      sync();
      fields.push(el("div", { style: "grid-column:1/-1" }, [
        el("label", { class: "switch" }, [hoursOn, el("span", { class: "switch-track" }),
          el("span", { text: "Only check during daylight hours (a panel's voltage naturally drops at night)" })]),
        hoursFields,
      ]));
    }

    rulesListEl.appendChild(el("div", { class: "rule-card" }, [
      el("div", { class: "rule-head" }, [
        el("span", { class: "rule-title", text: rule.label }),
        el("label", { class: "switch" }, [enabled, el("span", { class: "switch-track" }), el("span", { text: "Enabled" })]),
      ]),
      el("p", { class: "rule-help", text: rule.help }),
      el("div", { class: "rule-fields" }, fields),
    ]));

    return { rule: rule, enabled: enabled, threshold: threshold, severity: severity,
             confirmN: confirmN, hoursOn: hoursOn, from: from, to: to };
  });
}

async function loadRules() {
  renderRules(await api("/api/alert-rules"));
}

document.getElementById("rules-save").addEventListener("click", async () => {
  rulesErrorEl.textContent = "";
  const payload = ruleForms.map((f) => ({
    type: f.rule.type,
    enabled: f.enabled.checked,
    threshold: f.threshold.value,
    severity: f.severity.value,
    confirm_n: f.rule.type === "device_offline" ? f.rule.confirm_n : f.confirmN.value,
    active_from: f.hoursOn && f.hoursOn.checked ? f.from.value : "",
    active_to: f.hoursOn && f.hoursOn.checked ? f.to.value : "",
  }));
  try {
    renderRules(await api("/api/alert-rules", { method: "PUT", json: payload }));
    toast("Rules saved.", "ok");
  } catch (e) { rulesErrorEl.textContent = e.message; }
});

// ========================================================== notifications tab
const $ = (id) => document.getElementById(id);
const notifyErrorEl = $("notify-error");

function setSecret(input, isSet) {
  input.value = "";
  input.dataset.touched = "";
  input.placeholder = isSet ? "Saved. Leave blank to keep it." : "";
}
document.querySelectorAll(".secret").forEach((input) => {
  input.addEventListener("input", () => { input.dataset.touched = "1"; });
});

function fillNotifications(c) {
  $("n-minsev").value = c.min_severity;
  $("n-cooldown").value = c.cooldown_s;
  $("n-resolve").checked = c.notify_on_resolve;
  $("w-enabled").checked = c.webhook.enabled;
  $("w-format").value = c.webhook.format;
  setSecret($("w-url"), c.webhook.url_set);
  $("t-enabled").checked = c.telegram.enabled;
  $("t-chat").value = c.telegram.chat_id;
  setSecret($("t-token"), c.telegram.bot_token_set);
  $("e-enabled").checked = c.email.enabled;
  $("e-host").value = c.email.host;
  $("e-port").value = c.email.port;
  $("e-security").value = c.email.security;
  $("e-user").value = c.email.username;
  $("e-from").value = c.email.from;
  $("e-to").value = c.email.to;
  setSecret($("e-pass"), c.email.password_set);
}

// An untouched secret is sent as null, which the server reads as "keep it".
function secretValue(input) { return input.dataset.touched ? input.value : null; }

function collectNotifications() {
  return {
    min_severity: $("n-minsev").value,
    cooldown_s: $("n-cooldown").value,
    notify_on_resolve: $("n-resolve").checked,
    webhook: { enabled: $("w-enabled").checked, format: $("w-format").value, url: secretValue($("w-url")) },
    telegram: { enabled: $("t-enabled").checked, chat_id: $("t-chat").value, bot_token: secretValue($("t-token")) },
    email: {
      enabled: $("e-enabled").checked, host: $("e-host").value, port: $("e-port").value,
      security: $("e-security").value, username: $("e-user").value, from: $("e-from").value,
      to: $("e-to").value, password: secretValue($("e-pass")),
    },
  };
}

async function saveNotifications() {
  notifyErrorEl.textContent = "";
  try {
    fillNotifications(await api("/api/notifications", { method: "PUT", json: collectNotifications() }));
    return true;
  } catch (e) {
    notifyErrorEl.textContent = e.message;
    return false;
  }
}

$("notify-save").addEventListener("click", async () => {
  if (await saveNotifications()) toast("Notification settings saved.", "ok");
});

document.querySelectorAll(".test-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const channel = btn.dataset.test;
    const result = document.querySelector('[data-result="' + channel + '"]');
    result.className = "test-result";
    result.textContent = "";
    btn.disabled = true;
    try {
      if (!(await saveNotifications())) return;
      // Read the body even on failure: the server explains what went wrong.
      const res = await fetch("/api/notifications/test", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel: channel }),
      });
      const data = await res.json();
      result.className = "test-result " + (data.ok ? "ok" : "bad");
      result.textContent = data.ok ? "Sent. Check your " + CHANNEL_LABEL[channel] + "." : "Failed: " + data.detail;
    } catch (e) {
      result.className = "test-result bad";
      result.textContent = "Failed: " + e.message;
    } finally {
      btn.disabled = false;
      loadLog();
    }
  });
});

async function loadLog() {
  try {
    const rows = await api("/api/notifications/log");
    const body = $("log-body");
    body.textContent = "";
    $("log-empty").classList.toggle("hidden", rows.length > 0);
    rows.forEach((r) => {
      body.appendChild(el("tr", {}, [
        cell(formatTimestamp(r.ts), "nowrap"),
        cell(CHANNEL_LABEL[r.channel] || r.channel, "nowrap"),
        cell(r.event, "nowrap"),
        cell(el("span", {}, [
          el("span", { class: "badge " + (r.ok ? "state-ok" : "state-bad"), text: r.ok ? "OK" : "Failed" }),
          r.detail ? " " + r.detail : null,
        ])),
      ]));
    });
  } catch (e) { /* ignore */ }
}

async function loadNotifications() {
  fillNotifications(await api("/api/notifications"));
  loadLog();
}

// ===================================================================== tabs
const loaders = { alerts: loadAlerts, rules: loadRules, notifications: loadNotifications };
let currentTab = null;

let switching = 0;

async function showTab(name) {
  if (!TABS.includes(name)) name = "alerts";
  const mine = ++switching;
  // Load a tab's data BEFORE showing it. Otherwise someone could start typing
  // into a form that is about to be overwritten by the saved settings.
  if (!loaded[name]) {
    try { await loaders[name](); loaded[name] = true; } catch (e) { toast(e.message, "error"); }
  }
  if (mine !== switching) return;          // the user already clicked another tab
  currentTab = name;
  TABS.forEach((t) => document.getElementById("tab-" + t).classList.toggle("hidden", t !== name));
  tabButtons.forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  history.replaceState(null, "", name === "alerts" ? location.pathname : "#" + name);
}

tabButtons.forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));

showTab(location.hash.slice(1));
// Only the alert list refreshes by itself; the forms are left alone so
// nobody's half-typed settings get overwritten.
setInterval(() => { if (currentTab === "alerts" && !document.hidden) loadAlerts(); }, 3000);
