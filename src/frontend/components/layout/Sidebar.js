// Sidebar collapse/expand — M3 expandable navigation drawer
(function () {
  const STORAGE_KEY = "sidebar-collapsed";

  function applyCollapsed(collapsed) {
    const sidebar = document.getElementById("sidebar");
    if (!sidebar) return;
    sidebar.classList.toggle("sidebar-collapsed", collapsed);
    // Re-init lucide icons in case the toggle icon changed
    if (window.lucide) lucide.createIcons();
  }

  // Restore saved state on load
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved !== null) applyCollapsed(saved === "true");

  // Wire up toggle button
  document.addEventListener("click", function (e) {
    const btn = e.target.closest("#sidebar-toggle");
    if (!btn) return;
    const sidebar = document.getElementById("sidebar");
    const collapsed = !sidebar.classList.contains("sidebar-collapsed");
    applyCollapsed(collapsed);
    localStorage.setItem(STORAGE_KEY, String(collapsed));
  });
})();
