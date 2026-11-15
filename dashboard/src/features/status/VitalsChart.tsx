import { memo, useMemo, useState } from 'react'
import { crewIdentity } from '@/domain/crewConfig'
import { ToggleGroup } from '@/components/ui/toggle-group'
import { cn } from '@/lib/utils'
import type { CrewSample } from '@/telemetry/store'
import { useAllCrewHistory } from '@/telemetry/useTelemetry'

type Key = 'hr' | 'spo2' | 'core'
const METRICS: Record<Key, { label: string; unit: string; crit: number; dec: number }> = {
  hr: { label: 'Heart rate', unit: 'bpm', crit: 130, dec: 0 }, // ESTIMATE thresholds (status.ts)
  spo2: { label: 'SpO₂', unit: '%', crit: 90, dec: 0 },
  core: { label: 'Core temperature', unit: '°C', crit: 38.5, dec: 1 },
}
const W = 640, H = 220, PADL = 34, PADR = 86, PADT = 10, PADB = 22

function xLabel(sec: number) {
  if (sec < 90) return 'now'
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
    // keep every label inside the plot: push down from the top edge, then back up from the bottom edge
    const yTop = PADT + 6, yBottom = H - PADB - 4
    if (tips.length && tips[0].y < yTop) tips[0].y = yTop
    for (let i = 1; i < tips.length; i++) if (tips[i].y - tips[i - 1].y < 14) tips[i].y = tips[i - 1].y + 14
    if (tips.length && tips[tips.length - 1].y > yBottom) tips[tips.length - 1].y = yBottom
    for (let i = tips.length - 2; i >= 0; i--) if (tips[i + 1].y - tips[i].y < 14) tips[i].y = tips[i + 1].y - 14
    return { series, x, y, tips, span: tMax - tMin }
  }, [history, ids, key, meta.crit])

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-heading text-xl font-bold">{meta.label} <span className="font-sans text-sm font-normal text-muted-foreground">· one line per astronaut · {meta.unit}</span></h2>
        <ToggleGroup value={key} onChange={setKey} options={[{ value: 'hr', label: 'HR' }, { value: 'spo2', label: 'SpO₂' }, { value: 'core', label: 'Temp.' }]} />
      </div>
      {!model ? (
        <div className="grid h-[220px] place-items-center rounded-lg bg-muted text-sm text-muted-foreground">Waiting for data…</div>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxHeight: 210 }} role="img" aria-label={`Crew ${meta.label.toLowerCase()}`}>
          {(() => {
            const yc = model.y(meta.crit)
            const danger = key === 'spo2' ? [yc, H - PADB] : [PADT, yc]
            return <>
              <rect x={PADL} y={danger[0]} width={W - PADL - PADR} height={Math.max(0, danger[1] - danger[0])} fill="var(--status-danger)" fillOpacity={0.08} />
              <line x1={PADL} x2={W - PADR} y1={yc} y2={yc} stroke="var(--status-danger)" strokeDasharray="4 4" />
              <text x={PADL + 4} y={yc - 4} fontSize="11" className="fill-status-danger-foreground">soglia critica {meta.crit}</text>
            </>
          })()}
          {model.series.map((s) => s.pts.length > 0 && (
            <polyline key={s.id} fill="none" stroke={crewIdentity(s.id).color} strokeWidth={focus === s.id ? 2.6 : 1.7}
              opacity={focus && focus !== s.id ? 0.18 : 1} points={s.pts.map((p) => `${model.x(p.t).toFixed(1)},${model.y(p.v).toFixed(1)}`).join(' ')} />
          ))}
          {model.tips.map((t) => (
            <g key={t.id} opacity={focus && focus !== t.id ? 0.25 : 1}>
              <circle cx={W - PADR + 6} cy={t.y} r={3.5} fill={crewIdentity(t.id).color} />
              <text x={W - PADR + 14} y={t.y + 4} fontSize="12" fontWeight={500} className="fill-foreground">
                {crewIdentity(t.id).label} {t.v.toFixed(meta.dec)}
              </text>
            </g>
          ))}
          <text x={PADL} y={H - 4} fontSize="11" className="fill-muted-foreground">{xLabel(model.span)}</text>
          <text x={W - PADR} y={H - 4} fontSize="11" textAnchor="end" className="fill-muted-foreground">now</text>
        </svg>
      )}
      <div className="mt-2 flex gap-2">
        {ids.map((id) => (
          <button key={id} type="button" aria-pressed={focus === id} onClick={() => setFocus(focus === id ? null : id)}
            className={cn('h-6 rounded-full border-[1.5px] px-3 text-xs font-bold text-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50', focus === id && 'bg-muted-strong')}
            style={{ borderColor: crewIdentity(id).color }}>{crewIdentity(id).label}</button>
        ))}
      </div>
    </div>
  )
})
