import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { BodyHologram } from '@/components/BodyHologram'
import { sexToHologram } from '@/domain/crewConfig'
import { organAdapter } from '@/domain/organAdapter'
import type { NPCState, SimulationTick } from '@/telemetry'

export interface Anchor { x: number; y: number }
export type Anchors = Partial<Record<string, Anchor>>

/** Reads organ positions (data-organ) relative to the frame; recomputed on resize. */
export function useOrganAnchors(ref: React.RefObject<HTMLElement | null>, deps: unknown[]): Anchors {
  const [anchors, setAnchors] = useState<Anchors>({})
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const calc = () => {
      const f = el.getBoundingClientRect()
      const out: Anchors = {}
      el.querySelectorAll<SVGGElement>('[data-organ]').forEach((g) => {
        const r = g.getBoundingClientRect()
        out[g.dataset.organ as string] = { x: r.left + r.width / 2 - f.left, y: r.top + r.height / 2 - f.top }
      })
      setAnchors(out)
    }
    calc()
    const ro = new ResizeObserver(calc)
    ro.observe(el)
    return () => ro.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return anchors
}

/** Hologram + identity pedestal + scan line. `children` render as an overlay (callouts). */
export function HologramFrame({ npc, tick, width, color, children, frameRef }: {
  npc: NPCState; tick: SimulationTick; width: number; color: string; children?: ReactNode; frameRef?: React.RefObject<HTMLDivElement | null>
}) {
  const organs = useMemo(() => organAdapter.toOrganVitals(npc, tick.modules[npc.module_id], tick), [npc, tick])
  const local = useRef<HTMLDivElement>(null)
  const ref = frameRef ?? local
  return (
    <div ref={ref} className="relative mx-auto" style={{ width }}>
      <BodyHologram sex={sexToHologram(npc.sex)} organs={organs} size={width} />
      <svg aria-hidden className="pointer-events-none absolute left-0 w-full" style={{ bottom: -6 }} viewBox="0 0 100 20" preserveAspectRatio="none" height={width * 0.16}>
        <ellipse cx="50" cy="10" rx="40" ry="6" fill="none" stroke={color} strokeOpacity={0.95} strokeWidth={1} vectorEffect="non-scaling-stroke" />
        <ellipse cx="50" cy="10" rx="30" ry="4" fill="none" stroke={color} strokeOpacity={0.5} strokeWidth={1} vectorEffect="non-scaling-stroke" />
      </svg>
      <div aria-hidden className="anim-scan pointer-events-none absolute inset-x-0 h-3.5 mix-blend-screen" style={{ background: 'linear-gradient(transparent, rgb(143 211 255 / .35), transparent)' }} />
      {children}
    </div>
  )
}
