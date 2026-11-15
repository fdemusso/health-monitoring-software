import { ALARM_METRIC, ENV_METRICS, limitStatus, type EnvMetric } from '@/domain/limits'
import { maxStatus, type Status } from '@/domain/status'
import type { ModuleState, SimulationTick } from '@/telemetry'

const CHECKED: EnvMetric[] = ['temp', 'rh', 'pio2', 'ppco2', 'pressure']

/** Worst status of a module: nominal limits, engine alarms and open emergencies. */
export function moduleStatus(tick: SimulationTick, m: ModuleState): Status {
  let st: Status = 'ok'
  const metrics = m.co_ppm > 0.5 ? [...CHECKED, 'co' as EnvMetric] : CHECKED
  for (const k of metrics) st = maxStatus(st, limitStatus(ENV_METRICS[k], ENV_METRICS[k].read(m)))
  for (const a of tick.alarms)
    if (a.module_id === m.id && ALARM_METRIC[a.metric.toLowerCase()]) st = maxStatus(st, a.severity === 'alarm' ? 'crit' : 'warn')
  for (const e of tick.emergencies)
    if (e.module_id === m.id && e.state !== 'cleared') st = maxStatus(st, e.severity === 'critical' && e.state === 'confirmed' ? 'crit' : 'warn')
  return st
}
