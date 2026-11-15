import { useMemo } from 'react'
import { BodyHologram } from '@/components/BodyHologram'
import { sexToHologram } from '@/domain/crewConfig'
import { organAdapter } from '@/domain/organAdapter'
import type { NPCState, SimulationTick } from '@/telemetry'

/** Hologram + identity pedestal + scan line. */
export function HologramFrame({ npc, tick, width, color }: { npc: NPCState; tick: SimulationTick; width: number; color: string }) {
  const organs = useMemo(() => organAdapter.toOrganVitals(npc, tick.modules[npc.module_id], tick), [npc, tick])
  return (
    <div className="relative mx-auto" style={{ width }}>
      <BodyHologram sex={sexToHologram(npc.sex)} organs={organs} size={width} />
      <svg aria-hidden className="pointer-events-none absolute left-0 w-full" style={{ bottom: -6 }} viewBox="0 0 100 20" preserveAspectRatio="none" height={width * 0.16}>
        <ellipse cx="50" cy="10" rx="40" ry="6" fill="none" stroke={color} strokeOpacity={0.95} strokeWidth={1} vectorEffect="non-scaling-stroke" />
        <ellipse cx="50" cy="10" rx="30" ry="4" fill="none" stroke={color} strokeOpacity={0.5} strokeWidth={1} vectorEffect="non-scaling-stroke" />
      </svg>
      <div aria-hidden className="anim-scan pointer-events-none absolute inset-x-0 h-3.5 mix-blend-screen" style={{ background: 'linear-gradient(transparent, color-mix(in oklab, var(--chart-1) 40%, transparent), transparent)' }} />
    </div>
  )
}
