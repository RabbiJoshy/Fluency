# iOS Safari Touch Event Handling — Spotify Button Fix

## Problem

The Spotify play button on flashcard backs didn't respond to taps on iOS Safari. Tapping did nothing — no console output, no errors. Worked fine on desktop.

## Environment

- Button is a `<button>` inside a `.sentence` div with `onclick="cycleExample(event)"`
- The `.card` element has `touch-action: none` (line 156 of style.css)
- Card has `touchstart`, `touchmove`, `touchend` listeners (all `{ passive: true }`) for swipe gestures
- The `touchstart` handler returns early for `.link-btn` and `[onclick]` elements, so `isDragging` is never set for button touches
- The `touchend` handler bails out when `isDragging` is false

## What didn't work

1. **Changing `<span>` to `<button>`** — no effect
2. **Adding `ontouchend` handler** — no effect (earlier attempt, details unclear)
3. **`pointer-events: none` on inner SVG** — no effect
4. **Guard in `cycleExample()` to ignore `.spotify-btn` clicks** — no effect
5. **Event delegation on the card via `addEventListener`** — touchstart/touchend handlers added to the card element did fire for other interactions, but we couldn't verify for the button because Safari Web Inspector console was broken for the remote connection
6. **Inline `ontouchstart`/`ontouchend` with tap detection** — the tap detection logic (`this._ts` set in touchstart, checked in touchend) silently failed, likely because `this._ts` wasn't being preserved correctly across the inline handler boundary

## What worked

**Inline `ontouchend` directly on the button, calling `spotifyPlayTrack()` immediately:**

```html
<button class="spotify-btn link-btn"
  onclick="event.stopPropagation(); spotifyPlayTrack(...)"
  ontouchend="event.stopPropagation(); event.preventDefault(); spotifyPlayTrack(...)">
```

- `onclick` handles desktop (click events fire normally there)
- `ontouchend` handles iOS (bypasses click synthesis entirely)
- `event.preventDefault()` in touchend suppresses the (unreliable) synthesized click to avoid double-fire
- `event.stopPropagation()` prevents the event from reaching the card's touch handlers
- `position: relative; z-index: 999` on the button ensures nothing covers it

## Root cause (best hypothesis)

iOS Safari doesn't reliably synthesize `click` events for `<button>` elements inside containers with `touch-action: none` combined with passive touch event listeners. The exact mechanism is unclear — the touch events DO reach the button (confirmed via `alert()` in `ontouchend`), but the synthesized `click` event never fires.

The breakdown-trigger `<div>` (also inside `.sentence` with its own inline `onclick`) reportedly works on iOS — so the issue may be specific to `<button>` elements, or to the button's position/nesting depth, or to an interaction between the button's `.link-btn` class and the card's touch handler early-return logic.

## Debugging notes

- Safari Web Inspector Console tab showed zero output despite being connected (Elements tab worked). This made console.log-based debugging impossible.
- The `alert()` approach was the breakthrough — it confirmed touchend fires on the button, proving the issue was click synthesis, not event delivery.
- The Python dev server (`python3 -m http.server 8765`) serves files from disk without restart; `BrokenPipeError` in its logs is harmless (browser closing connections on reload).
- The service worker uses network-first strategy, so caching wasn't the issue when testing against the local server.

## Broader lesson

For iOS Safari touch handling inside `touch-action: none` containers: don't rely on click synthesis. Use `ontouchend` directly for the mobile path, with `onclick` as the desktop fallback.
