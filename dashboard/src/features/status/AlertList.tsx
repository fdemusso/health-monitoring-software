import { CrewChip, ModuleChip } from '@/components/CrewChip'
import { StatusDot } from '@/components/StatusDot'
import { emergencyTitle } from '@/domain/emergencyText'
import { crewStatus, type Status } from '@/domain/status'
import { sortCrewIds } from '@/domain/crewConfig'
import { fmt0, fmt1 } from '@/domain/units'
import type { SimulationTick } from '@/telemetry'

interface Row { key: string; status: Status; chip: React.ReactNode; text: string; sub: string }

export function AlertList({ tick }: { tick: SimulationTick }) {
  const rows: Row[] = []
  const ago = (t: number) => { const m = Math.max(0, Math.round((tick.t_sim_s - t) / 60)); return m < 1 ? 'ora' : `${m} min fa` }
  for (const e of tick.emergencies.filter((x) => x.state !== 'cleared'))
    rows.push({ key: e.id, status: e.severity === 'critical' ? 'crit' : 'warn', chip: e.subject ? <CrewChip id={e.subject} /> : <ModuleChip id={e.module_id} />, text: emergencyTitle(e), sub: `${e.module_id.toUpperCase()} · ${ago(e.t_open_s)}${e.state === 'suspected' ? ' · in verifica' : ''}` })
  tick.alarms.forEach((a, i) => rows.push({ key: `a${i}`, status: a.severity === 'alarm' ? 'crit' : 'warn', chip: <ModuleChip id={a.module_id} />, text: `${a.metric} fuori limite (${fmt1(a.value)})`, sub: `${a.module_id.toUpperCase()} · ${a.code}` }))
  for (const id of sortCrewIds(Object.keys(tick.npcs))) {
    const n = tick.npcs[id], st = crewStatus(n, tick.emergencies)
    if (st !== 'ok' && !rows.some((r) => r.key === id)) rows.push({ key: id, status: st, chip: <CrewChip id={id} />, text: `Vitali fuori range · FC ${fmt0(n.vitals.hr)}, SpO₂ ${fmt0(n.vitals.spo2)}`, sub: n.module_id.toUpperCase() })
  }
  return (
    <div>
      <h2 className="lbl mb-2">Avvisi attivi</h2>
      {rows.length === 0 ? <p className="text-sm text-muted-foreground">Nessun avviso.</p> : (
        <ul className="space-y-2">
          {rows.slice(0, 4).map((r) => (
            <li key={r.key} className="flex items-start gap-3 rounded-2xl border bg-white/[.02] p-3">
              <StatusDot status={r.status} className="mt-2" />
              <div className="min-w-0"><div className="flex items-center gap-2">{r.chip}<span className="truncate text-sm">{r.text}</span></div><div className="mt-0.5 text-xs text-muted-foreground">{r.sub}</div></div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
