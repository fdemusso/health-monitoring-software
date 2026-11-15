import { useEffect, useRef, useState, type MouseEvent, type PointerEvent } from 'react'
import { setFrozen } from '@/lib/dragFreeze'

/** Distance kept between a moved panel and the screen edge, px. */
const MARGIN = 28
/** Hold still this long (ms) on a panel to pick it up. */
const HOLD_MS = 350
/** A finger that moves more than this (px) before the hold is over is scrolling, not picking the panel up. */
const SLOP = 10
/** Where a press does not pick the panel up: the control itself needs the gesture. */
const OWN_GESTURE = 'input, select, textarea, [role="slider"]'

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi)

interface Held { px: number; py: number; ox: number; oy: number; rect: DOMRect }

/**
 * A floating panel that is picked up by pressing and holding it (mouse or finger), moved, and dropped by letting go: no handles.
 * `ref` and `style` (its `translate`) go on the panel, `panelProps` too (it must be the element that moves), and `data-drag-active`
 * marks it while it is held (index.css draws the highlighted border).
 * `centered`: the panel is centred with `left/top: 50%` and needs the -50 % shift in its `translate` as well.
 *
 * While held the panel is moved straight on the DOM, once per frame (`translate` is composited: no layout, no React render of the
 * panel's content). React gets the final position on release. The rest of the app stands still meanwhile (lib/dragFreeze.ts).
 * The panel cannot leave the screen. The position goes back to the layout one when `resetKey` changes (e.g. a dialog opens)
 * and when the screen width changes (rotation), so a panel is never stranded off-screen.
 */
export function useDraggable<T extends HTMLElement>(resetKey?: unknown, { centered = false }: { centered?: boolean } = {}) {
  const ref = useRef<T>(null)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const [dragging, setDragging] = useState(false)
  const live = useRef({ x: 0, y: 0 }) // where the panel is right now (the state only changes on release)
  const frame = useRef(0)
  const timer = useRef(0)
  const press = useRef<{ x: number; y: number; id: number } | null>(null) // a press waiting for the hold to complete
  const held = useRef<Held | null>(null)
  const swallowClick = useRef(false)

  const translate = (x: number, y: number) => (centered ? `calc(-50% + ${x}px) calc(-50% + ${y}px)` : `${x}px ${y}px`)
  const place = (x: number, y: number) => { live.current = { x, y }; setOffset({ x, y }) }

  // Once a finger is down the browser decides at its first move whether it scrolls: a listener added NOW (not at pick-up) can still veto it.
  const vetoScroll = (e: TouchEvent) => { if (held.current && e.cancelable) e.preventDefault() }

  const drop = () => {
    clearTimeout(timer.current)
    press.current = null
    ref.current?.removeEventListener('touchmove', vetoScroll)
    if (!held.current) return
    held.current = null
    cancelAnimationFrame(frame.current)
    frame.current = 0
    const el = ref.current
    if (el) el.style.willChange = ''
    document.body.style.userSelect = ''
    setFrozen(false)
    setOffset({ ...live.current }) // React takes over from the DOM position
    setDragging(false)
    swallowClick.current = true // the release after a hold is not a click on whatever is under the finger
    setTimeout(() => { swallowClick.current = false }, 0)
  }

  useEffect(() => { place(0, 0) }, [resetKey])
  useEffect(() => {
    let w = window.innerWidth
    const onResize = () => { if (window.innerWidth !== w) { w = window.innerWidth; place(0, 0) } }
    window.addEventListener('resize', onResize)
    return () => { window.removeEventListener('resize', onResize); clearTimeout(timer.current); cancelAnimationFrame(frame.current); setFrozen(false) }
  }, [])

  const pickUp = () => {
    const el = ref.current, p = press.current
    if (!el || !p) return
    el.setPointerCapture(p.id)
    held.current = { px: p.x, py: p.y, ox: live.current.x, oy: live.current.y, rect: el.getBoundingClientRect() }
    el.style.willChange = 'translate'
    document.body.style.userSelect = 'none'
    setFrozen(true)
    setDragging(true)
    navigator.vibrate?.(12) // a tick where the device has a motor (not iOS)
  }

  const panelProps = {
    onPointerDown: (e: PointerEvent<HTMLElement>) => {
      if ((e.pointerType === 'mouse' && e.button !== 0) || (e.target as HTMLElement).closest(OWN_GESTURE)) return
      press.current = { x: e.clientX, y: e.clientY, id: e.pointerId }
      ref.current?.addEventListener('touchmove', vetoScroll, { passive: false })
      clearTimeout(timer.current)
      timer.current = window.setTimeout(pickUp, HOLD_MS)
    },
    onPointerMove: (e: PointerEvent<HTMLElement>) => {
      const h = held.current
      if (!h) {
        const p = press.current
        if (p && Math.hypot(e.clientX - p.x, e.clientY - p.y) > SLOP) { clearTimeout(timer.current); press.current = null } // scrolling
        return
      }
      const dx = clamp(e.clientX - h.px, MARGIN - h.rect.left, window.innerWidth - MARGIN - h.rect.right)
      const dy = clamp(e.clientY - h.py, MARGIN - h.rect.top, window.innerHeight - MARGIN - h.rect.bottom)
      live.current = { x: h.ox + dx, y: h.oy + dy }
      if (frame.current) return // one write per frame, with the latest position
      frame.current = requestAnimationFrame(() => {
        frame.current = 0
        if (ref.current) ref.current.style.translate = translate(live.current.x, live.current.y)
      })
    },
    onPointerUp: drop,
    onPointerCancel: drop,
    onLostPointerCapture: drop,
    // a long press must not open the system menu or select the text under the finger
    onContextMenu: (e: MouseEvent) => { if (press.current || held.current) e.preventDefault() },
    onClickCapture: (e: MouseEvent) => { if (swallowClick.current) { e.stopPropagation(); e.preventDefault() } },
  }
  return { ref, style: { translate: translate(offset.x, offset.y) }, dragging, panelProps }
}
