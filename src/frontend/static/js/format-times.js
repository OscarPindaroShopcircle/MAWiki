// Format all <time> elements to local timezone.
// Called on page load and after htmx swaps.
function formatTimes(root = document) {
  root.querySelectorAll("time[datetime]").forEach((el) => {
    const dt = new Date(el.getAttribute("datetime"));
    if (isNaN(dt)) return;
    el.textContent = dt.toLocaleString(undefined, {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  });
}

document.addEventListener("DOMContentLoaded", () => formatTimes());
document.body.addEventListener("htmx:afterSwap", (e) => formatTimes(e.target));
