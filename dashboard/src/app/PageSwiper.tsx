import { useEffect, useRef, type ReactNode } from 'react'
import { useUi } from './ui-context'

/** Horizontal scroll-snap container; page index is kept in the UI context. */
export function PageSwiper({ pages }: { pages: ReactNode[] }) {
  const ref = useRef<HTMLDivElement>(null)
  const { page, setPage } = useUi()

  useEffect(() => {
    const el = ref.current
    if (el && Math.round(el.scrollLeft / el.clientWidth) !== page) el.scrollTo({ left: page * el.clientWidth, behavior: 'smooth' })
  }, [page])

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight') setPage(1)
      if (e.key === 'ArrowLeft') setPage(0)
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [setPage])

  return (
    <div
      ref={ref}
      className="no-scrollbar relative z-[2] flex min-h-0 flex-1 snap-x snap-mandatory overflow-x-auto"
      onScroll={(e) => {
        const el = e.currentTarget
        const p = Math.round(el.scrollLeft / el.clientWidth) as 0 | 1
        if (p !== page) setPage(p)
      }}
    >
      {pages.map((p, i) => (
        <section key={i} className="no-scrollbar w-full flex-none snap-start overflow-y-auto">{p}</section>
      ))}
    </div>
  )
}
