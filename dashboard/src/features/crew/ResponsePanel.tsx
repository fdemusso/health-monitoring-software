import { useState } from 'react'
import { CrewChip } from '@/components/CrewChip'
import { Button } from '@/components/ui/button'
import { Sheet } from '@/components/ui/sheet'
import { sortCrewIds } from '@/domain/crewConfig'
import { cn } from '@/lib/utils'
import { emergencyTitle, phaseLabel } from '@/domain/emergencyText'
import type { Emergency, SimulationTick } from '@/telemetry'
import { GuidedSteps } from './GuidedSteps'
import { PendingActionCard } from './PendingActionCard'
import { pickProtocol } from './protocols'

/** Response column. `crewId` scopes it to one astronaut; `emergencyIds` to module-level emergencies. */
export function ResponsePanel({ tick, crewId, emergency, className }: { tick: SimulationTick; crewId?: string; emergency?: Emergency | null; className?: string }) {
  const [earth, setEarth] = useState(false)
  const live = tick.emergencies.filter((e) => e.state !== 'cleared')
  const mine = emergency ? [emergency] : live.filter((e) => (crewId ? e.subject === crewId || (!e.subject && tick.npcs[crewId]?.module_id === e.module_id) : false))
  const ids = new Set(mine.map((e) => e.id))
  const pending = tick.pending_actions.filter((p) => ids.has(p.action.emergency_id))
  const npc = crewId ? tick.npcs[crewId] : undefined
  const protocol = pickProtocol(npc, mine)
  return (
    <aside aria-label="Response" className={cn('flex min-w-0 flex-col gap-4 rounded-lg border border-border bg-card p-4', className)}>
      <div>
        <div className="lbl">{mine.length ? 'Emergency response' : 'Routine'}</div>
        {mine.length > 0 && <h2 className="mt-1 font-heading text-xl font-bold">{emergencyTitle(mine[0])}</h2>}
      </div>
      {pending.length > 0 && (
        <div className="space-y-2">
          <div className="lbl">Awaiting confirmation</div>
          {pending.map((p) => <PendingActionCard key={p.action.id} pa={p} tSim={tick.t_sim_s} />)}
        </div>
      )}
      <GuidedSteps key={`${crewId}-${protocol.id}`} protocol={protocol} />
      <Button variant="outline" onClick={() => setEarth(true)}>Contact Earth</Button>
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
      <Sheet open={earth} onClose={() => setEarth(false)} title="Teleconsult" width={360}>
        <p className="text-sm text-muted-foreground">Teleconsult not connected. The link to Earth is not available in this version.</p>
      </Sheet>
    </aside>
  )
}
