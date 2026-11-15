import { CornerBrackets } from '@/components/CornerBrackets'
import { StatusBadge } from '@/components/ui/status-badge'
import { moduleName } from '@/domain/names'
import { crewIdentity } from '@/domain/crewConfig'
import { activityLabel, phaseLabel, ROLE_LABEL } from '@/domain/emergencyText'
import { crewStatus, statusLabel, statusText, vitalStatus } from '@/domain/status'
import { fmt0, fmt1 } from '@/domain/units'
import { useElementWidth } from '@/lib/useElementWidth'
import { cn } from '@/lib/utils'
import type { NPCState, SimulationTick } from '@/telemetry'
import { HologramFrame } from './HologramFrame'

export function CrewColumn({ npc, tick, onOpen }: { npc: NPCState; tick: SimulationTick; onOpen: () => void }) {
  const id = crewIdentity(npc.id)
  const st = crewStatus(npc, tick.emergencies)
  const [ref, w] = useElementWidth()
  const phase = phaseLabel(npc.response_phase)
  const v = npc.vitals
  return (
    <article
      className={cn('relative flex min-w-0 flex-col rounded-lg border border-border bg-card p-4 text-left transition-colors hover:bg-muted/50 has-focus-visible:ring-3 has-focus-visible:ring-ring/50', st === 'warn' && 'border-status-warning', st === 'crit' && 'border-status-danger bg-status-danger-soft')}
    >
      <CornerBrackets />
      <div className="mb-2 flex items-center justify-between">
        <span className="lbl">{moduleName(npc.module_id)}</span>
        <StatusBadge status={st}>{statusLabel[st]}</StatusBadge>
      </div>
      <div ref={ref} className="flex min-h-0 flex-1 items-center justify-center overflow-hidden px-2">
        {w > 0 && <HologramFrame npc={npc} tick={tick} width={Math.min(w, 200)} color={id.color} />}
      </div>
      <h3 className="mt-3 flex items-center gap-2 font-heading text-2xl font-bold">
        <span aria-hidden className="size-2.5 rounded-full" style={{ background: id.color }} />
        {/* the button covers the whole card (after:inset-0): one tap target, valid markup */}
        <button type="button" onClick={onOpen} aria-label={`Open details for ${id.person}, ${statusLabel[st].toLowerCase()}`} className="outline-none after:absolute after:inset-0 after:content-['']">{id.first}</button>
      </h3>
      <p className="mb-2 min-h-4 text-xs text-muted-foreground"><span className="sr-only">{id.name}: </span>{phase ? `${phase}${npc.role ? ` · ${ROLE_LABEL[npc.role] ?? npc.role}` : ''}` : activityLabel(npc.activity)}</p>
      <p className="flex gap-4 text-sm font-medium tabular-nums">
        <span className={statusText[vitalStatus('hr', v.hr, npc.activity)]}>{fmt0(v.hr)}<small className="ml-0.5 text-xs font-normal text-muted-foreground">bpm</small></span>
        <span className={statusText[vitalStatus('spo2', v.spo2)]}>{fmt0(v.spo2)}<small className="ml-0.5 text-xs font-normal text-muted-foreground">%</small></span>
        <span className={statusText[vitalStatus('core_temp_c', v.core_temp_c)]}>{fmt1(v.core_temp_c)}<small className="ml-0.5 text-xs font-normal text-muted-foreground">°C</small></span>
      </p>
    </article>
  )
}
