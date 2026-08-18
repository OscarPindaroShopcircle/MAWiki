// Sidebar collapse/expand + keyboard navigation — M3 navigation drawer
(function () {
  if (window.__circeusSidebar) return;
  window.__circeusSidebar = true;

  var STORAGE_KEY = "sidebar-collapsed";

  function getSidebar() {
    return document.getElementById("sidebar");
  }

  function applyCollapsed(collapsed) {
    var sidebar = getSidebar();
    if (!sidebar) return;
    sidebar.classList.toggle("sidebar-collapsed", collapsed);
    if (window.lucide) lucide.createIcons();
  }

  var saved = localStorage.getItem(STORAGE_KEY);
  if (saved !== null) applyCollapsed(saved === "true");

  document.addEventListener("click", function (e) {
    var btn = e.target.closest("#sidebar-toggle");
    if (!btn) return;
    var sidebar = getSidebar();
    var collapsed = !sidebar.classList.contains("sidebar-collapsed");
    applyCollapsed(collapsed);
    localStorage.setItem(STORAGE_KEY, String(collapsed));
  });

  // [ focuses the sidebar navigation
  document.addEventListener("keydown", function (e) {
    if (e.key !== "[" || e.target.matches("input, textarea, [contenteditable]")) return;
    var sidebar = getSidebar();
    if (!sidebar) return;
    var nav = sidebar.querySelector(".sidebar-nav");
    if (nav) nav.focus();
    e.preventDefault();
  });

  // Sidebar-local keyboard shortcuts
  document.addEventListener("keydown", function (e) {
    var sidebar = getSidebar();
    if (!sidebar || !sidebar.contains(document.activeElement)) return;

    // Shift+Left/Right collapse/expand
    if (e.shiftKey && e.key === "ArrowLeft") {
      applyCollapsed(true);
      localStorage.setItem(STORAGE_KEY, "true");
      e.preventDefault();
      return;
    }
    if (e.shiftKey && e.key === "ArrowRight") {
      applyCollapsed(false);
      localStorage.setItem(STORAGE_KEY, "false");
      e.preventDefault();
      return;
    }

    var links = Array.from(sidebar.querySelectorAll(".sidebar-link"));
    if (!links.length) return;
    var index = links.indexOf(document.activeElement);
    if (index === -1) {
      if (e.key === "ArrowDown") {
        links[0].focus();
        e.preventDefault();
      }
      return;
    }
    var next = null;
    if (e.key === "ArrowDown") next = (index + 1) % links.length;
    if (e.key === "ArrowUp") next = (index - 1 + links.length) % links.length;
    if (e.key === "Home") next = 0;
    if (e.key === "End") next = links.length - 1;
    if (next !== null) {
      links[next].focus();
      e.preventDefault();
    }
  });
})();
