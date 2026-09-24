# Target Window Upgrade

Two changes to the Target HUD panel:

1. **Ship portrait** -- when your target is a player ship or an NPC, its
   own sprite (the same art used in the world) is drawn as a translucent
   watermark on the right side of the panel, behind the text readout.
   Non-ship targets (stations, asteroids, planets, gates, dungeons, the
   sun) keep the plain text-only layout for now.
2. **Swapped right-click actions** -- plain right-click on the Target
   panel now does the old Shift+right-click "engage/pursue" behavior, and
   Shift+right-click now does the old plain-right-click "snapshot and fly
   to a fixed point" behavior. Note: the V / Shift+V keyboard shortcuts
   use the exact same two underlying functions by design, so they get
   swapped the same way -- V now engages/pursues, Shift+V now does a
   fixed snapshot fly-to.
