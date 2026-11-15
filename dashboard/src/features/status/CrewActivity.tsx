import { CrewChip, ModuleChip } from '@/components/CrewChip'
import { StatusDot } from '@/components/StatusDot'
import { sortCrewIds } from '@/domain/crewConfig'
import { activityLabel, phaseLabel, ROLE_LABEL } from '@/domain/emergencyText'
import { crewStatus } from '@/domain/status'
import { fmt1 } from '@/domain/units'
import type { SimulationTick } from '@/telemetry'

/**
 * What each astronaut is doing and where: always available (`activity`, `module_id`, `met` are in every tick).
 * During an emergency the response phase and role replace the scheduled activity.
 */
export function CrewActivity({ tick }: { tick: SimulationTick }) {
  const ids = sortCrewIds(Object.keys(tick.npcs))
  return (
    <div>
      <h2 className="mb-2 font-heading text-xl font-bold">Crew activity</h2>
      <ul className="space-y-2">
        {ids.map((id) => {
          const n = tick.npcs[id]
          const phase = n.response_phase ? phaseLabel(n.response_phase) : null
          return (
            <li key={id} className="flex items-center gap-3 rounded-lg border border-border bg-card px-3 py-2">
              <CrewChip id={id} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">
                  {phase ?? activityLabel(n.activity)}
                  {phase && n.role && <span className="font-normal text-muted-foreground"> · {ROLE_LABEL[n.role] ?? n.role}</span>}
                </div>
                <div className="text-xs text-muted-foreground tabular-nums">{fmt1(n.met)} MET</div>
              </div>
              <ModuleChip id={n.module_id} />
              <StatusDot status={crewStatus(n, tick.emergencies)} />
            </li>
          )
        })}
      </ul>
    </div>
  )
}
