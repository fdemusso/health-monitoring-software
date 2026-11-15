import { CrewChip, ModuleChip } from '@/components/CrewChip'
import { StatusDot } from '@/components/StatusDot'
import { emergencyTitle } from '@/domain/emergencyText'
import { crewStatus, type Status } from '@/domain/status'
import { sortCrewIds } from '@/domain/crewConfig'
import { fmt0, fmt1 } from '@/domain/units'
import { useUi } from '@/app/ui-context'
import { Button } from '@/components/ui/button'
import type { Emergency, SimulationTick } from '@/telemetry'

export interface AlertRow { key: string; status: Status; chip: React.ReactNode; text: string; sub: string; emergency?: Emergency }

/** Every active emergency, engine alarm and out-of-range crew member, in that order. */
export function alertRows(tick: SimulationTick): AlertRow[] {
  const rows: AlertRow[] = []
  const ago = (t: number) => { const m = Math.max(0, Math.round((tick.t_sim_s - t) / 60)); return m < 1 ? 'ora' : `${m} min fa` }
  for (const e of tick.emergencies.filter((x) => x.state !== 'cleared'))
    rows.push({ key: e.id, status: e.severity === 'critical' ? 'crit' : 'warn', chip: e.subject ? <CrewChip id={e.subject} /> : <ModuleChip id={e.module_id} />, emergency: e, text: emergencyTitle(e), sub: `${e.module_id.toUpperCase()} · ${ago(e.t_open_s)}${e.state === 'suspected' ? ' · in verifica' : ''}` })
  tick.alarms.forEach((a, i) => rows.push({ key: `a${i}`, status: a.severity === 'alarm' ? 'crit' : 'warn', chip: <ModuleChip id={a.module_id} />, text: `${a.metric} fuori limite (${fmt1(a.value)})`, sub: `${a.module_id.toUpperCase()} · ${a.code}` }))
  for (const id of sortCrewIds(Object.keys(tick.npcs))) {
    const n = tick.npcs[id], st = crewStatus(n, tick.emergencies)
    if (st !== 'ok' && !rows.some((r) => r.key === id)) rows.push({ key: id, status: st, chip: <CrewChip id={id} />, text: `Vitali fuori range · FC ${fmt0(n.vitals.hr)}, SpO₂ ${fmt0(n.vitals.spo2)}`, sub: n.module_id.toUpperCase() })
  }
  return rows
}

export function AlertList({ tick }: { tick: SimulationTick }) {
  const ui = useUi()
  const rows = alertRows(tick)
  return (
    <div>
      <h2 className="mb-2 font-heading text-xl font-bold">Avvisi attivi</h2>
      {rows.length === 0 ? <p className="text-sm text-muted-foreground">Nessun avviso.</p> : (
        <ul className="space-y-2">
          {rows.slice(0, 4).map((r) => (
            <li key={r.key} className="flex items-start gap-3 rounded-lg border border-border bg-card p-3">
              <StatusDot status={r.status} className="mt-2" />
              <div className="min-w-0"><div className="flex items-center gap-2">{r.chip}<span className="truncate text-sm">{r.text}</span></div><div className="mt-0.5 text-xs text-muted-foreground">{r.sub}</div></div>
            </li>
          ))}
        </ul>
      )}
      {rows.length > 4 && <Button variant="outline" className="mt-2" onClick={() => ui.setAlertsOpen(true)}>Tutti gli avvisi ({rows.length})</Button>}
    </div>
  )
}
