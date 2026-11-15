/**
 * While a panel is being dragged the rest of the app stands still: the telemetry store stops notifying (it catches up once on release)
 * and the CSS animations behind are paused (`html[data-dragging]` in index.css). The page keeps receiving ten frames a second and has
 * several infinite animations (hologram glow, scan line, breathing vignette): on a tablet that repaint competes with the finger.
 */
let frozen = false
const onThaw = new Set<() => void>()

export const isFrozen = () => frozen
/** `cb` runs when the freeze ends. */
export const whenThawed = (cb: () => void) => { onThaw.add(cb) }

export function setFrozen(on: boolean) {
  if (frozen === on) return
  frozen = on
  if (on) document.documentElement.dataset.dragging = ''
  else {
    delete document.documentElement.dataset.dragging
    for (const cb of onThaw) cb()
  }
}
