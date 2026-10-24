// Runs on every page: keeps the Alerts tab badge current and pops up a
// toast when a NEW alert appears (alerts already open at page load stay quiet).

(function () {
  const badge = document.getElementById("alert-badge");
  let lastSeenId = null;

  async function poll() {
    try {
      const s = await api("/api/alerts/summary");
      badge.textContent = s.unacknowledged;
      badge.classList.toggle("hidden", s.unacknowledged === 0);
      if (lastSeenId !== null && s.latest_id > lastSeenId && s.newest.length) {
        const newest = s.newest[0];
        toast(newest.message, newest.severity === "critical" ? "error" : "warning", "/alerts");
      }
      lastSeenId = s.latest_id;
    } catch (e) { /* server briefly unreachable: the dashboard shows that itself */ }
  }

  poll();
  setInterval(poll, 5000);
})();
