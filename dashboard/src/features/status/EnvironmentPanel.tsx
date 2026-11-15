import { useMemo } from 'react'
import { CrewChip } from '@/components/CrewChip'
import { Sparkline } from '@/components/Sparkline'
import { StatusDot } from '@/components/StatusDot'
import { StatusBadge } from '@/components/ui/status-badge'
import { ToggleGroup } from '@/components/ui/toggle-group'
import { ALARM_METRIC, ENV_METRICS, limitStatus, type EnvMetric } from '@/domain/limits'
import { maxStatus, primaryEmergency, statusText, type Status } from '@/domain/status'
import { cn } from '@/lib/utils'
import type { SimulationTick } from '@/telemetry'
import { useModuleHistory } from '@/telemetry/useTelemetry'

const BASE: EnvMetric[] = ['temp', 'rh', 'pio2', 'ppco2', 'pressure']

function Tile({ metric, tick, moduleId }: { metric: EnvMetric; tick: SimulationTick; moduleId: string }) {
  const spec = ENV_METRICS[metric]
  const m = tick.modules[moduleId]
  const hist = useModuleHistory(moduleId)
  const values = useMemo(() => (hist ?? []).map((s) => s[metric === 'temp' ? 'temp' : metric] as number), [hist, metric])
  const v = spec.read(m)
  let st: Status = limitStatus(spec, v)
  for (const a of tick.alarms)
    if (a.module_id === moduleId && ALARM_METRIC[a.metric.toLowerCase()] === metric) st = maxStatus(st, a.severity === 'alarm' ? 'crit' : 'warn')
  return (
    <div className="min-w-0 border-l border-border px-4 first:border-l-0 first:pl-0">
      <div className="lbl flex items-center gap-2 font-medium">{spec.label} <StatusDot status={st} /></div>
      <div className={cn('num mt-1 text-5xl leading-none', st !== 'ok' && statusText[st])}>
        {Number.isFinite(v) ? v.toFixed(spec.decimals) : '—'}<span className="ml-1 font-sans text-sm font-normal text-muted-foreground">{spec.unit}</span>
      </div>
      <div className="mb-1.5 mt-1 text-xs text-muted-foreground">{spec.nominal}</div>
      <Sparkline values={values} status={st} />
    </div>
  )
}

/** Module shown by default: emergency module, else the most occupied one. */
export function defaultModule(tick: SimulationTick, chosen: string | null): string | undefined {
  const ids = Object.keys(tick.modules)
  if (chosen && tick.modules[chosen]) return chosen
  const { primary } = primaryEmergency(tick.emergencies)
  if (primary && tick.modules[primary.module_id]) return primary.module_id
  return [...ids].sort((a, b) => tick.modules[b].occupants.length - tick.modules[a].occupants.length)[0]
}

export function EnvironmentHead({ tick, chosen, onChoose }: { tick: SimulationTick; chosen: string | null; onChoose: (id: string) => void }) {
  const moduleId = defaultModule(tick, chosen)
  if (!moduleId) return null
  const m = tick.modules[moduleId]
  // Modules with occupants or an emergency first.
  const hot = new Set(tick.emergencies.filter((e) => e.state !== 'cleared').map((e) => e.module_id))
  const sorted = Object.keys(tick.modules).sort((a, b) => Number(hot.has(b) || tick.modules[b].occupants.length > 0) - Number(hot.has(a) || tick.modules[a].occupants.length > 0))
  return (
    <div className="flex flex-wrap items-center gap-3">
      <span className="text-sm font-medium">Environment of</span>
      <div className="no-scrollbar max-w-full overflow-x-auto"><ToggleGroup joined className="flex-nowrap [&>button]:shrink-0" value={moduleId} onChange={onChoose} options={sorted.map((id) => ({ value: id, label: id.toUpperCase() }))} /></div>
      <span className="ml-2 text-sm font-medium">Occupants</span>
      {m.occupants.length ? m.occupants.map((o) => <CrewChip key={o} id={o} />) : <span className="text-xs text-muted-foreground">none</span>}
      {!m.fans_on && <StatusBadge status="warn">ventilation off</StatusBadge>}
    </div>
  )
}

export function EnvironmentTiles({ tick, chosen }: { tick: SimulationTick; chosen: string | null }) {
  const moduleId = defaultModule(tick, chosen)
  if (!moduleId) return null
  const m = tick.modules[moduleId]
  const showCo = m.co_ppm > 0.5 || tick.emergencies.some((e) => e.module_id === moduleId && e.state !== 'cleared' && (e.kind === 'toxic' || e.kind === 'fire'))
  const metrics = showCo ? [...BASE, 'co' as EnvMetric] : BASE
  return (
    <div className="grid" style={{ gridTemplateColumns: `repeat(${metrics.length}, minmax(0, 1fr))` }}>
      {metrics.map((k) => <Tile key={k} metric={k} tick={tick} moduleId={moduleId} />)}
    </div>
  )
}
