import { Move } from 'lucide-react'
import { useEffect, useRef, useState, type PointerEvent } from 'react'
import { cn } from '@/lib/utils'

/** Distance kept between a moved panel (handles included) and the screen edge, px. */
const MARGIN = 28

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi)

/**
 * Lets a floating panel be moved by its corner handles (mouse or finger: Pointer Events + pointer capture).
 * `ref` goes on the panel, `offset` is how far it was moved from where it is laid out (px), `handleProps` go on the handles.
 * The panel cannot leave the screen. The position goes back to the layout one when `resetKey` changes (e.g. a dialog opens)
 * and when the screen width changes (rotation), so a panel is never stranded off-screen.
 */
export function useDraggable<T extends HTMLElement>(resetKey?: unknown) {
  const ref = useRef<T>(null)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const [dragging, setDragging] = useState(false)
  const drag = useRef<{ px: number; py: number; ox: number; oy: number; rect: DOMRect } | null>(null)

  useEffect(() => { setOffset({ x: 0, y: 0 }) }, [resetKey])
  useEffect(() => {
    let w = window.innerWidth
    const onResize = () => { if (window.innerWidth !== w) { w = window.innerWidth; setOffset({ x: 0, y: 0 }) } }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const handleProps = {
    onPointerDown: (e: PointerEvent<HTMLElement>) => {
      const el = ref.current
      if (!el) return
      e.currentTarget.setPointerCapture(e.pointerId)
      drag.current = { px: e.clientX, py: e.clientY, ox: offset.x, oy: offset.y, rect: el.getBoundingClientRect() }
      setDragging(true)
      e.preventDefault()
    },
    onPointerMove: (e: PointerEvent<HTMLElement>) => {
      const d = drag.current
      if (!d) return
      const dx = clamp(e.clientX - d.px, MARGIN - d.rect.left, window.innerWidth - MARGIN - d.rect.right)
      const dy = clamp(e.clientY - d.py, MARGIN - d.rect.top, window.innerHeight - MARGIN - d.rect.bottom)
      setOffset({ x: d.ox + dx, y: d.oy + dy })
    },
    onPointerUp: () => { drag.current = null; setDragging(false) },
    onPointerCancel: () => { drag.current = null; setDragging(false) },
  }
  return { ref, offset, dragging, handleProps }
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
