// Small helpers shared by every page. Nothing here touches page-specific
// elements. User-supplied text (device names etc.) must only ever be put on
// the page with textContent, never innerHTML, so it can't inject markup.

async function api(path, options) {
  const opts = Object.assign({ headers: {} }, options || {});
  if (opts.json !== undefined) {
    opts.method = opts.method || "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.json);
    delete opts.json;
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    throw new Error("Can't reach the server. Is it still running?");
  }
  let data = null;
  try { data = await res.json(); } catch (e) { /* not JSON */ }
  if (!res.ok) {
    throw new Error((data && data.error) || "Request failed (" + res.status + ").");
  }
  return data;
}

function el(tag, attrs, children) {
  const node = document.createElement(tag);
  Object.keys(attrs || {}).forEach((key) => {
    const value = attrs[key];
    if (value === null || value === undefined || value === false) return;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  });
  [].concat(children || []).forEach((child) => {
    if (child === null || child === undefined || child === false) return;
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  });
  return node;
}

function toast(message, kind, href) {
  const root = document.getElementById("toast-root");
  const node = el("div", { class: "toast toast-" + (kind || "info"), role: "status", text: message });
  if (href) {
    node.style.cursor = "pointer";
    node.addEventListener("click", () => { window.location.href = href; });
  }
  root.appendChild(node);
  setTimeout(() => node.remove(), kind === "error" ? 9000 : 6000);
}

function confirmDialog(message, okLabel) {
  const dialog = document.getElementById("confirm-dialog");
  document.getElementById("confirm-text").textContent = message;
  document.getElementById("confirm-ok").textContent = okLabel || "OK";
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), { once: true });
    dialog.showModal();
  });
}

function formatDuration(seconds) {
  seconds = Math.max(0, Math.round(seconds));
  if (seconds < 60) return seconds + " s";
  if (seconds < 3600) return Math.floor(seconds / 60) + " min";
  if (seconds < 86400) {
    const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60);
    return h + " h" + (m ? " " + m + " min" : "");
  }
  const d = Math.floor(seconds / 86400), h = Math.floor((seconds % 86400) / 3600);
  return d + " d" + (h ? " " + h + " h" : "");
}

function formatTimestamp(epochSeconds) {
  if (!epochSeconds) return "-";
  return new Date(epochSeconds * 1000).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

function formatBytes(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1048576) return (bytes / 1024).toFixed(0) + " KB";
  return (bytes / 1048576).toFixed(1) + " MB";
}

function formatEnergy(wh) {
  return wh >= 1000 ? (wh / 1000).toFixed(2) + " kWh" : wh.toFixed(1) + " Wh";
}

function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text);
  }
  // http:// on a LAN address isn't a "secure context", so fall back.
  const area = el("textarea", { style: "position:fixed;opacity:0" });
  area.value = text;
  document.body.appendChild(area);
  area.select();
  try { document.execCommand("copy"); } finally { area.remove(); }
  return Promise.resolve();
}
