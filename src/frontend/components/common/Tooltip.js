(function () {
  if (window.__circeusTooltip) return;
  window.__circeusTooltip = true;

  var surface = document.createElement('div');
  surface.className = 'tooltip-surface';
  surface.setAttribute('role', 'tooltip');
  surface.setAttribute('popover', 'manual');
  document.body.appendChild(surface);
  var active = null;

  function position() {
    if (!active) return;
    var anchor = active.getBoundingClientRect();
    var gap = 8;
    var left = anchor.left + (anchor.width - surface.offsetWidth) / 2;
    var top = anchor.top - surface.offsetHeight - gap;
    var position = active.dataset.tooltipPosition;
    if (position === 'bottom' || top < gap) top = anchor.bottom + gap;
    left = Math.max(gap, Math.min(left, window.innerWidth - surface.offsetWidth - gap));
    surface.style.left = left + 'px';
    surface.style.top = top + 'px';
  }

  function show(anchor) {
    active = anchor;
    surface.textContent = anchor.dataset.tooltip;
    if (!surface.matches(':popover-open')) surface.showPopover();
    position();
    surface.classList.add('tooltip-surface-visible');
  }

  function hide(anchor) {
    if (anchor && anchor !== active) return;
    surface.classList.remove('tooltip-surface-visible');
    if (surface.matches(':popover-open')) surface.hidePopover();
    active = null;
  }

  document.addEventListener('pointerover', function (event) {
    var anchor = event.target.closest('[data-tooltip]');
    if (anchor && !anchor.contains(event.relatedTarget)) show(anchor);
  });
  document.addEventListener('pointerout', function (event) {
    var anchor = event.target.closest('[data-tooltip]');
    if (anchor && !anchor.contains(event.relatedTarget)) hide(anchor);
  });
  document.addEventListener('focusin', function (event) {
    var anchor = event.target.closest('[data-tooltip]');
    if (anchor) show(anchor);
  });
  document.addEventListener('focusout', function (event) {
    var anchor = event.target.closest('[data-tooltip]');
    if (anchor && !anchor.contains(event.relatedTarget)) hide(anchor);
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') hide();
  });
  window.addEventListener('resize', position);
  window.addEventListener('scroll', position, true);
})();
