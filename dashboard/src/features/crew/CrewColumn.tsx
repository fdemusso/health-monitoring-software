import { useEffect, useRef, useState } from 'react'
import { CornerBrackets } from '@/components/CornerBrackets'
import { Badge } from '@/components/ui/badge'
import { crewIdentity } from '@/domain/crewConfig'
import { activityLabel, phaseLabel, ROLE_LABEL } from '@/domain/emergencyText'
import { crewStatus, statusLabel, statusText, vitalStatus } from '@/domain/status'
import { fmt0, fmt1 } from '@/domain/units'
import { cn } from '@/lib/utils'
import type { NPCState, SimulationTick } from '@/telemetry'
import { HologramFrame } from './HologramFrame'

export function useElementWidth(external?: React.RefObject<HTMLDivElement | null>) {
  const own = useRef<HTMLDivElement>(null)
  const ref = external ?? own
  const [w, setW] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setW(Math.floor(e.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, w] as const
}

export function CrewColumn({ npc, tick, onOpen }: { npc: NPCState; tick: SimulationTick; onOpen: () => void }) {
  const id = crewIdentity(npc.id)
  const st = crewStatus(npc, tick.emergencies)
  const [ref, w] = useElementWidth()
  const phase = phaseLabel(npc.response_phase)
  const v = npc.vitals
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`Apri dettaglio ${id.label}, ${statusLabel[st].toLowerCase()}`}
      className={cn('relative flex min-w-0 flex-col rounded-3xl border p-4 text-left transition active:scale-[.98]', st === 'warn' && 'border-warn/50', st === 'crit' && 'border-crit/70')}
      style={{ background: st === 'crit' ? 'linear-gradient(180deg, hsl(4 100% 62% / .12), transparent 70%)' : 'radial-gradient(120% 60% at 50% 40%, rgb(94 211 255 / .07), transparent 70%)' }}
    >
      <CornerBrackets />
      <div className="mb-2 flex items-center justify-between">
        <span className="lbl">{npc.module_id}</span>
        <Badge tone={st}>{statusLabel[st]}</Badge>
      </div>
      <div ref={ref} className="flex min-h-0 flex-1 items-center justify-center overflow-hidden px-2">
        {w > 0 && <HologramFrame npc={npc} tick={tick} width={Math.min(w, 200)} color={id.color} />}
      </div>
      <div className="mt-3 text-2xl tracking-[.22em]" style={{ color: id.color }}>{id.label}</div>
      <div className="mb-2 min-h-4 text-xs text-muted-foreground">{phase ? `${phase}${npc.role ? ` · ${ROLE_LABEL[npc.role] ?? npc.role}` : ''}` : activityLabel(npc.activity)}</div>
      <div className="flex gap-4 font-mono text-sm tabular-nums">
        <span className={statusText[vitalStatus('hr', v.hr, npc.activity)]}>{fmt0(v.hr)}<small className="ml-0.5 text-muted-foreground">bpm</small></span>
        <span className={statusText[vitalStatus('spo2', v.spo2)]}>{fmt0(v.spo2)}<small className="ml-0.5 text-muted-foreground">%</small></span>
        <span className={statusText[vitalStatus('core_temp_c', v.core_temp_c)]}>{fmt1(v.core_temp_c)}<small className="ml-0.5 text-muted-foreground">°C</small></span>
      </div>
    </button>
  )
}
