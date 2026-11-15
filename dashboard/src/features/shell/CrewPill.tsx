import { CrewChip } from '@/components/CrewChip'
import { StatusDot } from '@/components/StatusDot'
import { crewIdentity } from '@/domain/crewConfig'
import { crewStatus, statusLabel } from '@/domain/status'
import { fmt0 } from '@/domain/units'
import { cn } from '@/lib/utils'
import type { Emergency, NPCState } from '@/telemetry'

export function CrewPill({ npc, emergencies, onOpen }: { npc: NPCState; emergencies: Emergency[]; onOpen: () => void }) {
  const st = crewStatus(npc, emergencies)
  const spo2 = npc.vitals.spo2
  const spo2Crit = spo2 != null && spo2 < 90
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`Apri dettaglio ${crewIdentity(npc.id).label}, ${statusLabel[st].toLowerCase()}`}
      className={cn(
        'flex min-w-0 items-center gap-3 rounded-full border border-border bg-card py-2 pl-2 pr-4 transition-colors outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50',
        st === 'warn' && 'border-status-warning bg-status-warning-soft', st === 'crit' && 'border-status-danger bg-status-danger-soft',
      )}
    >
      <CrewChip id={npc.id} />
      <span className="text-xs tabular-nums text-muted-foreground">{fmt0(npc.vitals.hr)} bpm</span>
      <span className={cn('text-xs tabular-nums', spo2Crit ? 'font-medium text-status-danger-foreground' : 'text-muted-foreground')}>{fmt0(spo2)} %</span>
      <StatusDot status={st} />
    </button>
  )
}
