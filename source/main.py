"""Target Window Upgrade:

1. Renders the targeted ship's own sprite (the same art used in the world,
   via the game's cached self._get_ship_img) as a translucent portrait
   inside the Target panel, instead of text-only readouts.
2. Swaps the right-click / Shift+right-click actions on the Target panel:
   plain right-click now does the old Shift+right-click "engage/pursue"
   behavior, and Shift+right-click now does the old plain-right-click
   "snapshot fly-to" behavior.

Part 1 approach:
  * The Target panel is drawn via a generic, shared self._draw_panel(...)
    helper (used by many HUD panels), called from a local closure buried
    deep inside Client.py's main render method -- there's no standalone
    "_draw_target_panel" method to patch. So this patches _draw_panel
    itself and special-cases pid == "target", leaving every other panel
    that shares the same renderer (inventory, vitals, chat, ...)
    untouched.
  * The portrait is drawn AFTER calling the original (so it doesn't get
    erased by the panel's own opaque background fill), as a low-alpha
    watermark anchored to the panel's right edge. It only appears for
    ship targets (player ships and NPCs) -- stations/asteroids/planets
    keep the plain text layout for now.
  * Panel geometry for positioning comes from self._panel_full_rects,
    which is one frame stale by the time we read it (this frame's own
    _draw_panel call hasn't updated it yet) -- imperceptible for a
    HUD panel that barely moves.

Part 2 approach:
  * The two underlying methods, _snapshot_target_autopilot and
    _activate_target_autopilot, are also both what the V / Shift+V
    keyboard shortcuts call (by design -- see _activate_target_autopilot's
    own docstring, "Handle V and the target panel Shift+right-click
    shortcut"). Swapping them at the method level therefore swaps V and
    Shift+V the same way, since there's no separate, patchable code path
    for "only the mouse buttons" -- the click handler's few lines live
    inline in the same giant method as everything else and call these
    same two functions directly. If you want the keyboard shortcuts left
    alone, say so and this can be revisited (it would mean re-implementing
    the engage/pursue logic independently, which is a bigger, riskier
    change).
"""

import threading

_icons_cache = {}
_original_draw_panel = None
_original_snapshot_autopilot = None
_original_activate_autopilot = None
_patched_class = None


def _resolve_target_ship_type(host):
    npc_id = getattr(host, "_targeted_npc_id", None)
    if npc_id is not None:
        with host._lock:
            npc = host._npc_entities.get(npc_id)
        return npc.get("ship_type") if npc else None

    pid = getattr(host, "_targeted_pid", None)
    if pid is not None:
        with host._lock:
            ent = host._remote_entities.get(pid)
        return ent.get("ship_type") if ent else None

    return None


def _get_scaled_portrait(host, pygame, ship_type, max_w, max_h):
    key = (ship_type, max_w, max_h)
    cached = _icons_cache.get(key)
    if cached is not None:
        return cached

    try:
        raw = host._get_ship_img(ship_type)
    except Exception:
        raw = None
    if raw is None:
        _icons_cache[key] = False
        return None

    raw_w, raw_h = raw.get_size()
    if raw_w <= 0 or raw_h <= 0:
        _icons_cache[key] = False
        return None

    scale = min(max_w / raw_w, max_h / raw_h)
    new_w = max(1, int(raw_w * scale))
    new_h = max(1, int(raw_h * scale))
    scaled = pygame.transform.smoothscale(raw, (new_w, new_h)).convert_alpha()
    scaled.set_alpha(115)
    _icons_cache[key] = scaled
    return scaled


def _draw_target_portrait(host, pygame, ctx):
    ship_type = _resolve_target_ship_type(host)
    if not ship_type:
        return
    rect = host._panel_full_rects.get("target")
    if rect is None or rect.width <= 0 or rect.height <= 0:
        return

    max_h = max(1, rect.height - host._s(16))
    max_w = max(1, int(rect.width * 0.4))
    portrait = _get_scaled_portrait(host, pygame, ship_type, max_w, max_h)
    if not portrait:
        return

    dest = portrait.get_rect(
        midright=(rect.right - host._s(8), rect.centery))
    ctx.screen.blit(portrait, dest)


def _make_draw_panel(pygame, original):
    def patched(self, ctx, pid, title, body_lines, *args, **kwargs):
        result = original(self, ctx, pid, title, body_lines, *args, **kwargs)
        if pid == "target":
            _draw_target_portrait(self, pygame, ctx)
        return result

    return patched


_reentry_guard = threading.local()


def _make_swapped_snapshot(original_snapshot, original_activate):
    def swapped_snapshot(self):
        # _activate_target_autopilot(shift_pressed=True) and
        # _engage_nav_autopilot call self._snapshot_target_autopilot()
        # internally as part of their own engine logic (not just as the
        # V-key entry point). Once this method is swapped at the class
        # level, those internal calls would otherwise loop straight back
        # into original_activate(shift_pressed=True) forever. Only the
        # outermost, user-triggered call should be redirected to the
        # engage behavior; any nested call made from inside that engine
        # logic must fall through to the real, unswapped snapshot.
        if getattr(_reentry_guard, "active", False):
            return original_snapshot(self)
        _reentry_guard.active = True
        try:
            # Was: fly to a fixed snapshot of the target's position.
            # Now: perform the continuous engage/pursue behavior.
            return original_activate(self, shift_pressed=True)
        finally:
            _reentry_guard.active = False

    return swapped_snapshot


def _make_swapped_activate(original_snapshot, original_activate):
    def swapped_activate(self, *, shift_pressed: bool = False):
        if shift_pressed:
            if getattr(_reentry_guard, "active", False):
                return original_activate(self, shift_pressed=True)
            # Was: continuous engage/pursue.
            # Now: fly to a fixed snapshot of the target's position.
            return original_snapshot(self)
        return original_activate(self, shift_pressed=False)

    return swapped_activate


def _on_startup(host, pygame, screen):
    global _original_draw_panel, _original_snapshot_autopilot
    global _original_activate_autopilot, _patched_class

    cls = type(host)
    _patched_class = cls

    _original_draw_panel = cls._draw_panel
    cls._draw_panel = _make_draw_panel(pygame, _original_draw_panel)

    _original_snapshot_autopilot = cls._snapshot_target_autopilot
    _original_activate_autopilot = cls._activate_target_autopilot
    cls._snapshot_target_autopilot = _make_swapped_snapshot(
        _original_snapshot_autopilot, _original_activate_autopilot)
    cls._activate_target_autopilot = _make_swapped_activate(
        _original_snapshot_autopilot, _original_activate_autopilot)


def _on_shutdown(*_args, **_kwargs):
    if _patched_class is None:
        return
    if _original_draw_panel is not None:
        _patched_class._draw_panel = _original_draw_panel
    if _original_snapshot_autopilot is not None:
        _patched_class._snapshot_target_autopilot = _original_snapshot_autopilot
    if _original_activate_autopilot is not None:
        _patched_class._activate_target_autopilot = _original_activate_autopilot


def apply(api):
    api.on("client.startup", _on_startup)
    api.on("loader.shutdown", _on_shutdown)
    api.logger.info("target-window-upgrade ready, waiting for client.startup")
