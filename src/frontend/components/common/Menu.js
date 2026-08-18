(function () {
  if (window.__circeusMenu) return;
  window.__circeusMenu = true;

  function triggerFor(menu) {
    return document.getElementById(menu.getAttribute('aria-labelledby'));
  }

  function position(menu) {
    if (!menu.matches(':popover-open')) return;
    var trigger = triggerFor(menu);
    if (!trigger) return;
    var anchor = trigger.getBoundingClientRect();
    var gap = 4;
    var edge = 8;
    var placement = menu.dataset.menuPlacement;
    var top = placement.startsWith('top')
      ? anchor.top - menu.offsetHeight - gap
      : anchor.bottom + gap;
    if (top + menu.offsetHeight > window.innerHeight - edge) {
      top = anchor.top - menu.offsetHeight - gap;
    }
    if (top < edge) top = anchor.bottom + gap;
    var left = placement.endsWith('end')
      ? anchor.right - menu.offsetWidth
      : anchor.left;
    left = Math.max(edge, Math.min(left, window.innerWidth - menu.offsetWidth - edge));
    menu.style.top = Math.max(edge, top) + 'px';
    menu.style.left = left + 'px';
  }

  document.addEventListener('toggle', function (event) {
    var menu = event.target;
    if (!menu.matches || !menu.matches('[data-menu]')) return;
    var trigger = triggerFor(menu);
    var open = menu.matches(':popover-open');
    if (trigger) trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (!open) return;
    position(menu);
    var first = menu.querySelector('[role="menuitem"]:not([disabled])');
    if (first) first.focus();
  }, true);

  document.addEventListener('keydown', function (event) {
    var menu = event.target.closest('[data-menu]');
    if (!menu) return;
    var items = Array.from(menu.querySelectorAll('[role="menuitem"]:not([disabled])'));
    if (!items.length) return;
    var index = items.indexOf(document.activeElement);
    var next = null;
    if (event.key === 'ArrowDown') next = (index + 1) % items.length;
    if (event.key === 'ArrowUp') next = (index - 1 + items.length) % items.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = items.length - 1;
    if (event.key === 'Escape') {
      menu.hidePopover();
      var trigger = triggerFor(menu);
      if (trigger) trigger.focus();
      event.preventDefault();
    } else if (next !== null) {
      items[next].focus();
      event.preventDefault();
    }
  });

  function repositionOpenMenus() {
    document.querySelectorAll('[data-menu]:popover-open').forEach(position);
  }

  window.addEventListener('resize', repositionOpenMenus);
  window.addEventListener('scroll', repositionOpenMenus, true);
})();
