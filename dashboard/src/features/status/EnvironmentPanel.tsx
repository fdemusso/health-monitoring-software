import { ChevronDown, Users } from 'lucide-react'
import { Popover } from 'radix-ui'
import { useMemo, useState } from 'react'
import { CrewChip } from '@/components/CrewChip'
import { Sparkline } from '@/components/Sparkline'
import { StatusDot } from '@/components/StatusDot'
import { StatusBadge } from '@/components/ui/status-badge'
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

/** Worst status of a module: open emergencies and active alarms. */
function moduleStatus(tick: SimulationTick, id: string): Status {
  let st: Status = 'ok'
  for (const e of tick.emergencies) if (e.module_id === id && e.state !== 'cleared') st = maxStatus(st, e.alert_class === 'emergency' || e.alert_class === 'warning' ? 'crit' : 'warn')
  for (const a of tick.alarms) if (a.module_id === id) st = maxStatus(st, a.severity === 'alarm' ? 'crit' : 'warn')
  return st
}

function ModulePicker({ tick, value, onChange }: { tick: SimulationTick; value: string; onChange: (id: string) => void }) {
  const [open, setOpen] = useState(false)
  const ids = Object.keys(tick.modules)
  const status = moduleStatus(tick, value)
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button type="button" aria-label="Choose module" className="inline-flex h-8 items-center gap-2 rounded-control border border-input px-3 text-sm font-medium outline-none transition-colors hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 data-[state=open]:bg-muted">
          <StatusDot status={status} />
          {value.toUpperCase()}
          <ChevronDown className="size-4 text-muted-foreground" />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content align="start" sideOffset={6} className="z-50 w-[420px] max-w-[calc(100vw-2rem)] rounded-lg border border-border bg-card p-2 shadow-lg animate-in fade-in-0 zoom-in-95">
          <div className="grid grid-cols-4 gap-1">
            {ids.map((id) => {
              const st = moduleStatus(tick, id)
              const n = tick.modules[id].occupants.length
              const selected = id === value
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => { onChange(id); setOpen(false) }}
                  className={cn('flex h-9 items-center rounded-control px-2.5 text-left text-sm font-medium outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50',
                    selected ? 'bg-primary text-primary-foreground' : 'hover:bg-muted')}
                >
                  <span className="flex items-center gap-1.5">
                    {id.toUpperCase()}
                    {n > 0 && <Users className={cn('size-3.5', selected ? 'text-primary-foreground/70' : 'text-muted-foreground')} aria-label={`${n} in module`} />}
                    {st !== 'ok' && <StatusDot status={st} />}
                  </span>
                </button>
              )
            })}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}

export function EnvironmentHead({ tick, chosen, onChoose }: { tick: SimulationTick; chosen: string | null; onChoose: (id: string) => void }) {
  const moduleId = defaultModule(tick, chosen)
  if (!moduleId) return null
  const m = tick.modules[moduleId]
  return (
    <div className="flex flex-wrap items-center gap-3">
      <span className="text-sm font-medium">Environment of</span>
      <ModulePicker tick={tick} value={moduleId} onChange={onChoose} />
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
