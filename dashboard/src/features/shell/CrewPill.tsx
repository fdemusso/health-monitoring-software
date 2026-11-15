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
        'flex min-w-0 items-center gap-3 rounded-full border bg-white/[.02] py-2 pl-2 pr-4 transition active:scale-[.97]',
        st === 'warn' && 'border-warn/45', st === 'crit' && 'border-crit/70 bg-crit/10',
      )}
    >
      <CrewChip id={npc.id} />
      <span className="font-mono text-xs tabular-nums text-muted-foreground">{fmt0(npc.vitals.hr)} bpm</span>
      <span className={cn('font-mono text-xs tabular-nums', spo2Crit ? 'text-crit' : 'text-muted-foreground')}>{fmt0(spo2)} %</span>
      <StatusDot status={st} />
    </button>
  )
}
