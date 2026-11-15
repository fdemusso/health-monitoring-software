import { memo, useMemo, useState } from 'react'
import { crewIdentity } from '@/domain/crewConfig'
import { ToggleGroup } from '@/components/ui/toggle-group'
import { cn } from '@/lib/utils'
import type { CrewSample } from '@/telemetry/store'
import { useAllCrewHistory } from '@/telemetry/useTelemetry'

type Key = 'hr' | 'spo2' | 'core'
const METRICS: Record<Key, { label: string; unit: string; crit: number; dec: number }> = {
  hr: { label: 'Frequenza cardiaca', unit: 'bpm', crit: 130, dec: 0 }, // ESTIMATE thresholds (status.ts)
  spo2: { label: 'SpO₂', unit: '%', crit: 90, dec: 0 },
  core: { label: 'Temperatura core', unit: '°C', crit: 38.5, dec: 1 },
}
const W = 640, H = 220, PADL = 34, PADR = 70, PADT = 10, PADB = 22

function xLabel(sec: number) {
  if (sec < 90) return 'ora'
  return sec < 5400 ? `-${Math.round(sec / 60)} min` : `-${(sec / 3600).toFixed(1)} h`
}

export const VitalsChart = memo(function VitalsChart() {
  const history = useAllCrewHistory()
  const [key, setKey] = useState<Key>('hr')
  const [focus, setFocus] = useState<string | null>(null)
  const meta = METRICS[key]
  const ids = Object.keys(history)

  const model = useMemo(() => {
    const series = ids.map((id) => ({ id, pts: (history[id] as CrewSample[]).filter((s) => s[key] != null).map((s) => ({ t: s.t, v: s[key] as number })) }))
    const all = series.flatMap((s) => s.pts)
    if (!all.length) return null
    const tMax = Math.max(...all.map((p) => p.t)), tMin = Math.min(...all.map((p) => p.t))
    let lo = Math.min(...all.map((p) => p.v), meta.crit), hi = Math.max(...all.map((p) => p.v), meta.crit)
    const pad = (hi - lo || 1) * 0.12
    lo -= pad; hi += pad
    const x = (t: number) => PADL + (tMax === tMin ? 0 : ((t - tMin) / (tMax - tMin)) * (W - PADL - PADR))
    const y = (v: number) => PADT + (1 - (v - lo) / (hi - lo)) * (H - PADT - PADB)
    // tip labels with >= 14 px spacing
    const tips = series.filter((s) => s.pts.length).map((s) => ({ id: s.id, v: s.pts[s.pts.length - 1].v, y: y(s.pts[s.pts.length - 1].v) })).sort((a, b) => a.y - b.y)
    for (let i = 1; i < tips.length; i++) if (tips[i].y - tips[i - 1].y < 14) tips[i].y = tips[i - 1].y + 14
    return { series, x, y, tips, span: tMax - tMin }
  }, [history, ids, key, meta.crit])

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="lbl">{meta.label} · una linea per astronauta · {meta.unit}</h2>
        <ToggleGroup value={key} onChange={setKey} options={[{ value: 'hr', label: 'FC' }, { value: 'spo2', label: 'SpO₂' }, { value: 'core', label: 'Temp.' }]} />
      </div>
      {!model ? (
        <div className="grid h-[220px] place-items-center rounded-2xl bg-white/[.03] text-sm text-muted-foreground">In attesa dei dati…</div>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxHeight: 210 }} role="img" aria-label={`${meta.label} dell'equipaggio`}>
          {(() => {
            const yc = model.y(meta.crit)
            const danger = key === 'spo2' ? [yc, H - PADB] : [PADT, yc]
            return <>
              <rect x={PADL} y={danger[0]} width={W - PADL - PADR} height={Math.max(0, danger[1] - danger[0])} fill="hsl(4 100% 62% / .06)" />
              <line x1={PADL} x2={W - PADR} y1={yc} y2={yc} stroke="hsl(4 100% 62% / .6)" strokeDasharray="4 4" />
              <text x={PADL + 4} y={yc - 4} fontSize="10" fill="hsl(4 100% 62%)">soglia critica {meta.crit}</text>
            </>
          })()}
          {model.series.map((s) => s.pts.length > 0 && (
            <polyline key={s.id} fill="none" stroke={crewIdentity(s.id).color} strokeWidth={focus === s.id ? 2.6 : 1.7}
              opacity={focus && focus !== s.id ? 0.18 : 1} points={s.pts.map((p) => `${model.x(p.t).toFixed(1)},${model.y(p.v).toFixed(1)}`).join(' ')} />
          ))}
          {model.tips.map((t) => (
            <text key={t.id} x={W - PADR + 6} y={t.y + 4} fontSize="11" fontWeight={600} fill={crewIdentity(t.id).color} opacity={focus && focus !== t.id ? 0.25 : 1}>
              {crewIdentity(t.id).label} {t.v.toFixed(meta.dec)}
            </text>
          ))}
          <text x={PADL} y={H - 4} fontSize="10" fill="hsl(215 10% 56%)">{xLabel(model.span)}</text>
          <text x={W - PADR} y={H - 4} fontSize="10" textAnchor="end" fill="hsl(215 10% 56%)">ora</text>
        </svg>
      )}
      <div className="mt-2 flex gap-2">
        {ids.map((id) => (
          <button key={id} type="button" aria-pressed={focus === id} onClick={() => setFocus(focus === id ? null : id)}
            className={cn('rounded-full border px-3 py-1 text-[11px] font-bold tracking-[.1em]', focus === id && 'bg-white/10')}
            style={{ color: crewIdentity(id).color, borderColor: crewIdentity(id).color }}>{crewIdentity(id).label}</button>
        ))}
      </div>
    </div>
  )
})
