import { useEffect, useRef, useState, type RefObject } from 'react'

/** Width of an element in px, kept up to date. Pass your own `ref` when you need it elsewhere too. */
export function useElementWidth(external?: RefObject<HTMLDivElement | null>) {
  const own = useRef<HTMLDivElement>(null)
  const ref = external ?? own
  const [w, setW] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setW(Math.floor(e.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [ref])
  return [ref, w] as const
}
