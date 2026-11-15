import { useUi } from '@/app/ui-context'
import { CrewChip } from '@/components/CrewChip'
import { StatusBadge } from '@/components/ui/status-badge'
import { Dialog } from '@/components/ui/dialog'
import { moduleStatus } from '@/domain/moduleStatus'
import { RANKED, statusLabel, statusText, type Status } from '@/domain/status'
import { ENV_METRICS, limitStatus, type EnvMetric } from '@/domain/limits'
import { cn } from '@/lib/utils'
import type { ModuleState, SimulationTick } from '@/telemetry'
import { useTick } from '@/telemetry/useTelemetry'

const SHOWN: EnvMetric[] = ['temp', 'pressure', 'ppco2', 'pio2']

function Value({ m, k }: { m: ModuleState; k: EnvMetric }) {
  const spec = ENV_METRICS[k]
  const v = spec.read(m)
  const st: Status = limitStatus(spec, v)
  return (
    <div>
      <div className="text-xs text-muted-foreground">{spec.label}</div>
      <div className={cn('text-sm font-medium tabular-nums', st !== 'ok' && statusText[st])}>
        {Number.isFinite(v) ? v.toFixed(spec.decimals) : '—'}<span className="ml-0.5 text-xs font-normal text-muted-foreground">{spec.unit}</span>
      </div>
    </div>
  )
}

function ModuleCard({ tick, m, onPick }: { tick: SimulationTick; m: ModuleState; onPick: () => void }) {
  const st = moduleStatus(tick, m)
  return (
    <button
      type="button"
      onClick={onPick}
      className={cn(
        'flex flex-col gap-3 rounded-lg border border-border bg-card p-3 text-left outline-none transition-colors hover:bg-muted/50 focus-visible:ring-3 focus-visible:ring-ring/50',
        st === 'warn' && 'border-status-warning', st === 'crit' && 'border-status-danger bg-status-danger-soft',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-heading text-xl font-bold">{m.id.toUpperCase()}</span>
        <StatusBadge status={st}>{statusLabel[st]}</StatusBadge>
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-2">{SHOWN.map((k) => <Value key={k} m={m} k={k} />)}</div>
      <div className="flex min-h-6 flex-wrap items-center gap-1.5">
        {m.occupants.length ? m.occupants.map((o) => <CrewChip key={o} id={o} />) : <span className="text-xs text-muted-foreground">No occupants</span>}
        {!m.fans_on && <StatusBadge status="warn">ventilation off</StatusBadge>}
      </div>
    </button>
  )
}

/** Map of every module of the station: status, key values and who is inside. A card selects the module on the Status page. */
export function ModulesDialog() {
  const ui = useUi()
  const tick = useTick()
  const mods = tick ? Object.values(tick.modules).sort((a, b) => RANKED(moduleStatus(tick, b)) - RANKED(moduleStatus(tick, a)) || b.occupants.length - a.occupants.length || a.id.localeCompare(b.id)) : []
  return (
    <Dialog open={ui.modulesOpen} onClose={() => ui.setModulesOpen(false)} title="Modules" width={1040}>
      {tick && (
        <div className="grid grid-cols-4 gap-3">
          {mods.map((m) => <ModuleCard key={m.id} tick={tick} m={m} onPick={() => { ui.setModulesOpen(false); ui.setPage(0) }} />)}
        </div>
      )}
    </Dialog>
  )
}
