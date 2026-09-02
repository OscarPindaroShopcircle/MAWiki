document.body.addEventListener("htmx:afterSwap", (event) => {
  window.lucide?.createIcons({ root: event.target });
});
