import { useEffect, useRef, type ReactNode } from 'react'
import { useUi } from '../ui-context'

export interface SwiperPage { id: string; label: string; node: ReactNode }

/** Keys that belong to the control being used, never to the page switch. */
const OWN_ARROWS = 'input, select, textarea, [role="slider"], [role="dialog"]'

/** `<main>`: horizontal scroll-snap container; page index is kept in the UI context. The page that is not showing is `inert`
 *  (not focusable, not read out), so the keyboard and screen readers never land off-screen. */
export function PageSwiper({ pages }: { pages: SwiperPage[] }) {
  const ref = useRef<HTMLElement>(null)
  const { page, setPage } = useUi()

  useEffect(() => {
    const el = ref.current
    if (el && Math.round(el.scrollLeft / el.clientWidth) !== page) el.scrollTo({ left: page * el.clientWidth, behavior: 'smooth' })
  }, [page])

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest?.(OWN_ARROWS)) return
      if (e.key === 'ArrowRight') setPage(1)
      if (e.key === 'ArrowLeft') setPage(0)
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [setPage])

  return (
    <main
      id="main"
      ref={ref}
      tabIndex={-1}
      className="no-scrollbar relative z-[2] flex min-h-0 flex-1 snap-x snap-mandatory overflow-x-auto outline-none"
      onScroll={(e) => {
        const el = e.currentTarget
        const p = Math.round(el.scrollLeft / el.clientWidth) as 0 | 1
        if (p !== page) setPage(p)
      }}
    >
      <h1 className="sr-only">ARES 3 · {pages[page].label}</h1>
      {pages.map((p, i) => (
        <section key={p.id} aria-label={p.label} inert={i !== page} className="no-scrollbar w-full flex-none snap-start overflow-y-auto">{p.node}</section>
      ))}
    </main>
  )
}
