import { Move } from 'lucide-react'
import { useEffect, useRef, useState, type PointerEvent } from 'react'
import { setFrozen } from '@/lib/dragFreeze'
import { cn } from '@/lib/utils'

/** Distance kept between a moved panel (handles included) and the screen edge, px. */
const MARGIN = 28

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi)

/**
 * Lets a floating panel be moved by its corner handles (mouse or finger: Pointer Events + pointer capture).
 * `ref` goes on the panel, `style` (its `translate`) goes on the panel too, `handleProps` go on the handles.
 * `centered`: the panel is centred with `left/top: 50%` and needs the -50 % shift in its `translate` as well.
 *
 * While a finger is down the panel is moved straight on the DOM, once per frame (`translate` is composited: no layout, no React render
 * of the panel's content, which in the alarms list is hundreds of nodes updated ten times a second). React gets the final position on release.
 * The panel cannot leave the screen. The position goes back to the layout one when `resetKey` changes (e.g. a dialog opens)
 * and when the screen width changes (rotation), so a panel is never stranded off-screen.
 */
export function useDraggable<T extends HTMLElement>(resetKey?: unknown, { centered = false }: { centered?: boolean } = {}) {
  const ref = useRef<T>(null)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const [dragging, setDragging] = useState(false)
  const live = useRef({ x: 0, y: 0 }) // where the panel is right now (the state only changes on release)
  const frame = useRef(0)
  const drag = useRef<{ px: number; py: number; ox: number; oy: number; rect: DOMRect } | null>(null)

  const translate = (x: number, y: number) => (centered ? `calc(-50% + ${x}px) calc(-50% + ${y}px)` : `${x}px ${y}px`)
  const place = (x: number, y: number) => { live.current = { x, y }; setOffset({ x, y }) }

  useEffect(() => { place(0, 0) }, [resetKey])
  useEffect(() => {
    let w = window.innerWidth
    const onResize = () => { if (window.innerWidth !== w) { w = window.innerWidth; place(0, 0) } }
    window.addEventListener('resize', onResize)
    return () => { window.removeEventListener('resize', onResize); cancelAnimationFrame(frame.current); setFrozen(false) }
  }, [])

  const end = () => {
    if (!drag.current) return
    drag.current = null
    cancelAnimationFrame(frame.current)
    const el = ref.current
    if (el) el.style.willChange = ''
    document.body.style.userSelect = ''
    setFrozen(false)
    setOffset({ ...live.current }) // React takes over from the DOM position
    setDragging(false)
  }

  const handleProps = {
    onPointerDown: (e: PointerEvent<HTMLElement>) => {
      const el = ref.current
      if (!el) return
      e.currentTarget.setPointerCapture(e.pointerId)
      drag.current = { px: e.clientX, py: e.clientY, ox: live.current.x, oy: live.current.y, rect: el.getBoundingClientRect() }
      el.style.willChange = 'translate'
      document.body.style.userSelect = 'none'
      setFrozen(true)
      setDragging(true)
      e.preventDefault()
    },
    onPointerMove: (e: PointerEvent<HTMLElement>) => {
      const d = drag.current
      if (!d) return
      const dx = clamp(e.clientX - d.px, MARGIN - d.rect.left, window.innerWidth - MARGIN - d.rect.right)
      const dy = clamp(e.clientY - d.py, MARGIN - d.rect.top, window.innerHeight - MARGIN - d.rect.bottom)
      live.current = { x: d.ox + dx, y: d.oy + dy }
      if (frame.current) return // one write per frame, with the latest position
      frame.current = requestAnimationFrame(() => {
        frame.current = 0
        if (ref.current) ref.current.style.translate = translate(live.current.x, live.current.y)
      })
    },
    onPointerUp: end,
    onPointerCancel: end,
  }
  return { ref, style: { translate: translate(offset.x, offset.y) }, dragging, handleProps }
}

/** The two move handles, top-left and bottom-right, half outside the panel's corners (the panel must be `relative` or `fixed`). */
export function DragHandles({ handleProps, dragging }: { handleProps: ReturnType<typeof useDraggable>['handleProps']; dragging: boolean }) {
  const cls = cn(
    'absolute z-10 grid size-10 touch-none place-items-center rounded-full border border-border bg-card text-muted-foreground shadow-sm outline-none transition-colors hover:bg-muted',
    dragging ? 'cursor-grabbing bg-muted-strong' : 'cursor-grab',
  )
  return (
    <>
      <button type="button" tabIndex={-1} aria-label="Drag to move" className={cn(cls, '-left-5 -top-5')} {...handleProps}><Move className="size-5" /></button>
      <button type="button" tabIndex={-1} aria-label="Drag to move" className={cn(cls, '-bottom-5 -right-5')} {...handleProps}><Move className="size-5" /></button>
    </>
  )
}
