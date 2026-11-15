import { CrewChip, ModuleChip } from '@/components/CrewChip'
import { moduleName, METRIC_NAME } from '@/domain/names'
import { ALARM_METRIC } from '@/domain/limits'
import { emergencyTitle } from '@/domain/emergencyText'
import { crewStatus, type Status } from '@/domain/status'
import { sortCrewIds } from '@/domain/crewConfig'
import { fmt0, fmt1 } from '@/domain/units'
import type { Emergency, SimulationTick } from '@/telemetry'

export interface AlertRow { key: string; status: Status; chip: React.ReactNode; text: string; sub: string; emergency?: Emergency }

/** Every active emergency, engine alarm and out-of-range crew member, in that order. */
export function alertRows(tick: SimulationTick): AlertRow[] {
  const rows: AlertRow[] = []
  const ago = (t: number) => { const m = Math.max(0, Math.round((tick.t_sim_s - t) / 60)); return m < 1 ? 'now' : `${m} min ago` }
  for (const e of tick.emergencies.filter((x) => x.state !== 'cleared'))
    rows.push({ key: e.id, status: e.severity === 'critical' ? 'crit' : 'warn', chip: e.subject ? <CrewChip id={e.subject} /> : <ModuleChip id={e.module_id} />, emergency: e, text: emergencyTitle(e), sub: `${moduleName(e.module_id)} · ${ago(e.t_open_s)}${e.state === 'suspected' ? ' · being verified' : ''}` })
  tick.alarms.forEach((a, i) => rows.push({ key: `a${i}`, status: a.severity === 'alarm' ? 'crit' : 'warn', chip: <ModuleChip id={a.module_id} />, text: `${METRIC_NAME[ALARM_METRIC[a.metric.toLowerCase()]]?.label ?? a.metric} outside safe limits (${fmt1(a.value)})`, sub: moduleName(a.module_id) }))
  for (const id of sortCrewIds(Object.keys(tick.npcs))) {
    const n = tick.npcs[id], st = crewStatus(n, tick.emergencies)
    if (st !== 'ok' && !rows.some((r) => r.key === id)) rows.push({ key: id, status: st, chip: <CrewChip id={id} />, text: `Vital signs out of range · heart ${fmt0(n.vitals.hr)} bpm, blood oxygen ${fmt0(n.vitals.spo2)} %`, sub: moduleName(n.module_id) })
  }
  return rows
}
