import { Heart } from 'lucide-react'
import { CrewChip } from '@/components/CrewChip'
import { StatusDot } from '@/components/StatusDot'
import { crewIdentity } from '@/domain/crewConfig'
import { crewStatus, statusLabel } from '@/domain/status'
import { fmt0 } from '@/domain/units'
import { cn } from '@/lib/utils'
import type { Emergency, NPCState } from '@/telemetry'

export function CrewPill({ npc, emergencies, selected, onOpen }: { npc: NPCState; emergencies: Emergency[]; selected: boolean; onOpen: () => void }) {
  const st = crewStatus(npc, emergencies)
  const spo2 = npc.vitals.spo2
  const spo2Crit = spo2 != null && spo2 < 90
  const color = crewIdentity(npc.id).color
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-pressed={selected}
      style={selected ? { borderColor: color, boxShadow: `0 0 0 2px ${color}, 0 4px 14px -4px color-mix(in oklab, ${color} 55%, transparent)` } : undefined}
      aria-label={`Open details for ${crewIdentity(npc.id).person}, ${statusLabel[st].toLowerCase()}`}
      className={cn(
        'flex min-w-0 items-center gap-2 whitespace-nowrap rounded-full border border-border bg-card py-2 pl-2 pr-3 transition-[background-color,box-shadow,border-color,transform,opacity] duration-(--duration-enter) outline-none hover:bg-muted active:scale-[.97] focus-visible:ring-3 focus-visible:ring-ring/50',
        selected && 'bg-muted-strong',
        st === 'warn' && 'border-status-warning bg-status-warning-soft', st === 'crit' && 'border-status-danger bg-status-danger-soft',
      )}
    >
      <CrewChip id={npc.id} />
      <span className="flex items-center gap-1 text-xs tabular-nums text-muted-foreground" title="Heart rate, beats per minute"><Heart aria-hidden className="size-3" />{fmt0(npc.vitals.hr)}</span>
      <span title="Blood oxygen" className={cn('text-xs tabular-nums', spo2Crit ? 'font-medium text-status-danger-foreground' : 'text-muted-foreground')}>{fmt0(spo2)}%</span>
      <StatusDot status={st} />
    </button>
  )
}
