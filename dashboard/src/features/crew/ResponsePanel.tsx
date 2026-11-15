import { CrewChip } from '@/components/CrewChip'
import { ContactEarthButton } from './ContactEarthButton'
import { sortCrewIds } from '@/domain/crewConfig'
import { cn } from '@/lib/utils'
import { emergencyTitle, phaseLabel } from '@/domain/emergencyText'
import type { Emergency, SimulationTick } from '@/telemetry'
import { EmergencyProtocol } from './ProcedureView'
import { PendingActionCard } from './PendingActionCard'

/** The response to one emergency: pending confirmations, the protocol, what the crew is doing. */
export function ResponsePanel({ tick, emergency, className }: { tick: SimulationTick; emergency: Emergency; className?: string }) {
  const live = tick.emergencies.filter((e) => e.state !== 'cleared')
  const pending = tick.pending_actions.filter((p) => p.action.emergency_id === emergency.id)
  return (
    <aside aria-label="Response" className={cn('flex min-w-0 flex-col gap-4 rounded-lg border border-border bg-card p-4', className)}>
      <div>
        <div className="lbl">Emergency response</div>
        <h2 className="mt-1 font-heading text-xl font-bold">{emergencyTitle(emergency)}</h2>
      </div>
      {pending.length > 0 && (
        <div className="space-y-2">
          <div className="lbl">Awaiting confirmation</div>
          {pending.map((p) => <PendingActionCard key={p.action.id} pa={p} tSim={tick.t_sim_s} />)}
        </div>
      )}
      <EmergencyProtocol key={emergency.id} tick={tick} emergency={emergency} compact />
      <ContactEarthButton key={`earth-${emergency.id}`} />
      {live.length > 0 && (
        <div>
          <div className="lbl mb-2">What the crew is doing</div>
          <ul className="space-y-1.5">
            {sortCrewIds(Object.keys(tick.npcs)).map((id) => (
              <li key={id} className="flex items-center justify-between text-xs"><CrewChip id={id} /><span className="text-muted-foreground">{phaseLabel(tick.npcs[id].response_phase) ?? '—'}</span></li>
            ))}
          </ul>
        </div>
      )}
    </aside>
  )
}
