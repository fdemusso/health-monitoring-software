import { useEffect, useRef, useState } from 'react'

/** Pixel size of an element, kept up to date (the charts draw at their real size so they fill the free space). */
export function useElementSize<T extends HTMLElement>(initial = { w: 800, h: 300 }) {
  const ref = useRef<T>(null)
  const [size, setSize] = useState(initial)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const read = () => {
      const w = Math.round(el.clientWidth), h = Math.round(el.clientHeight)
      if (w > 0 && h > 0) setSize((s) => (s.w === w && s.h === h ? s : { w, h }))
    }
    read()
    const ro = new ResizeObserver(read)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return { ref, ...size }
}
