import { Clock } from 'lucide-react'
import { memo, useMemo, useRef, useState } from 'react'
import { crewIdentity, sortCrewIds } from '@/domain/crewConfig'
import { fmtHms } from '@/domain/units'
import { ToggleGroup } from '@/components/ui/toggle-group'
import { cn } from '@/lib/utils'
import { useElementSize } from '@/lib/useElementSize'
import type { CrewSample } from '@/telemetry/store'
import { useAllCrewHistory, useEventLog, useStore } from '@/telemetry/useTelemetry'
import type { AlertClass } from '@/telemetry/types'

type Key = 'hr' | 'spo2' | 'core'
interface Metric {
  label: string; unit: string; dec: number
  crit: number
  /** Normal band (ESTIMATE, to confirm with Luca; same spirit as domain/status.ts). */
  normal: [number, number]
  /** Default visible range; widened when the data leaves it, so the scale does not breathe tick by tick. */
  range: [number, number]
  step: number
  /** The danger zone is below the threshold (SpO2) or above it. */
  dangerBelow?: boolean
}
const METRICS: Record<Key, Metric> = {
  hr: { label: 'Heart rate', unit: 'bpm', dec: 0, crit: 130, normal: [50, 100], range: [40, 150], step: 20 },
  spo2: { label: 'Blood oxygen', unit: '%', dec: 0, crit: 90, normal: [95, 100], range: [85, 100], step: 5, dangerBelow: true },
  core: { label: 'Body temperature', unit: '°C', dec: 1, crit: 38.5, normal: [36.1, 37.8], range: [35.5, 39], step: 0.5 },
}

const WINDOWS = { '15m': 900, '1h': 3600, '6h': 21600 } as const
type Win = keyof typeof WINDOWS
/** Spacing of the time-axis labels, aligned to the clock on board (a label is always a round time). */
const X_STEP: Record<Win, number> = { '15m': 180, '1h': 600, '6h': 3600 }

const PADL = 44, PADR = 92, PADT = 14, PADB = 28

const CLASS_COLOR: Record<AlertClass, string> = {
  emergency: 'var(--status-danger)', warning: 'var(--status-warning)', caution: 'var(--status-info)', advisory: 'var(--status-info)',
}

/** Time of day on board from simulated seconds + the clock offset. */
const clock = (t: number, off: number) => fmtHms((t + off) % 86400)

interface Span { id: string; t0: number; t1: number | null; text: string; color: string }

export const VitalsChart = memo(function VitalsChart() {
  const history = useAllCrewHistory()
  const eventLog = useEventLog()
  const emergencies = useStore((s) => s.tick?.emergencies)
  const off = useStore((s) => s.clockOffsetS)
  const [key, setKey] = useState<Key>('hr')
  const [win, setWin] = useState<Win>('1h')
  const [focus, setFocus] = useState<string | null>(null)
  const [cursor, setCursor] = useState<number | null>(null) // sim time under the pointer
  const svgRef = useRef<SVGSVGElement>(null)
  const { ref: boxRef, w: W, h: Hraw } = useElementSize<HTMLDivElement>()
  const H = Math.max(200, Hraw), PW = W - PADL - PADR, PH = H - PADT - PADB
  const meta = METRICS[key]
  const ids = useMemo(() => sortCrewIds(Object.keys(history)), [history])

  const model = useMemo(() => {
    const series = ids.map((id) => ({
      id,
      pts: (history[id] as CrewSample[]).filter((s) => s[key] != null).map((s) => ({ t: s.t, v: s[key] as number })),
    }))
    const all = series.flatMap((s) => s.pts)
    if (!all.length) return null
    const tMax = Math.max(...all.map((p) => p.t))
    // the window never starts before the first sample: no empty stretch on the left while the history is still short
    const tFirst = Math.min(...all.map((p) => p.t))
    const tMin = Math.min(Math.max(tMax - WINDOWS[win], tFirst), tMax - 60)
    const vis = series.map((s) => ({ ...s, pts: s.pts.filter((p) => p.t >= tMin) }))
    const vals = vis.flatMap((s) => s.pts.map((p) => p.v))
    let lo = Math.min(meta.range[0], ...vals), hi = Math.max(meta.range[1], ...vals)
    lo = Math.floor(lo / meta.step) * meta.step; hi = Math.ceil(hi / meta.step) * meta.step
    const x = (t: number) => PADL + ((t - tMin) / (tMax - tMin)) * PW
    const y = (v: number) => PADT + (1 - (v - lo) / (hi - lo)) * PH
    const yTicks: number[] = []
    for (let v = lo; v <= hi + 1e-9; v += meta.step) yTicks.push(Number(v.toFixed(2)))
    const xTicks: number[] = []
    for (let t = Math.ceil((tMin + off) / X_STEP[win]) * X_STEP[win] - off; t <= tMax - X_STEP[win] * 0.25; t += X_STEP[win]) xTicks.push(t)

    // end-of-line labels, >= 18 px apart, kept inside the plot
    const GAP = 18
    const tips = vis.filter((s) => s.pts.length)
      .map((s) => { const v = s.pts[s.pts.length - 1].v; return { id: s.id, v, y: y(v) } })
      .sort((a, b) => a.y - b.y)
    const yTop = PADT + 8, yBottom = PADT + PH - 4
    for (let i = 1; i < tips.length; i++) if (tips[i].y - tips[i - 1].y < GAP) tips[i].y = tips[i - 1].y + GAP
    if (tips.length && tips[tips.length - 1].y > yBottom) tips[tips.length - 1].y = yBottom
    for (let i = tips.length - 2; i >= 0; i--) if (tips[i + 1].y - tips[i].y < GAP) tips[i].y = tips[i + 1].y - GAP
    if (tips.length && tips[0].y < yTop) tips[0].y = yTop
    return { series: vis, x, y, tips, tMin, tMax, lo, hi, yTicks, xTicks }
  }, [history, ids, key, win, meta, PW, PH, off])

  // Emergencies as spans on the time axis (opened ... cleared, or still open).
  const spans = useMemo<Span[]>(() => {
    const byId = new Map(emergencies?.map((e) => [e.id, e]))
    const open = new Map<string, Span>()
    const out: Span[] = []
    for (const e of eventLog) {
      if (!e.emergency_id) continue
      if (e.kind === 'emergency_opened') {
        const live = byId.get(e.emergency_id)
        const sp: Span = { id: e.emergency_id, t0: e.t_s, t1: null, text: e.message, color: CLASS_COLOR[live?.alert_class ?? 'warning'] }
        open.set(e.emergency_id, sp); out.push(sp)
      } else if (e.kind === 'emergency_cleared') {
        const sp = open.get(e.emergency_id)
        if (sp) sp.t1 = e.t_s
      }
    }
    return out
  }, [eventLog, emergencies])

  const visibleSpans = model ? spans.filter((s) => (s.t1 ?? model.tMax) >= model.tMin && s.t0 <= model.tMax) : []

  const onMove = (e: React.PointerEvent) => {
    if (!model || !svgRef.current) return
    const r = svgRef.current.getBoundingClientRect()
    const vx = ((e.clientX - r.left) / r.width) * W
    const t = model.tMin + ((vx - PADL) / PW) * (model.tMax - model.tMin)
    setCursor(Math.min(model.tMax, Math.max(model.tMin, t)))
  }

  // Tooltip data: the sample nearest to the cursor, per astronaut.
  const hover = model && cursor != null ? (() => {
    const rows = model.series.map((s) => {
      let best: { t: number; v: number } | null = null
      for (const p of s.pts) if (!best || Math.abs(p.t - cursor) < Math.abs(best.t - cursor)) best = p
      return best && { id: s.id, ...best }
    }).filter((r): r is { id: string; t: number; v: number } => r != null)
    if (!rows.length) return null
    const t = rows[0].t
    const events = visibleSpans.filter((s) => t >= s.t0 && t <= (s.t1 ?? Infinity))
    return { t, rows, events, left: ((model.x(t)) / W) * 100 }
  })() : null

  const latest = (id: string) => {
    const pts = model?.series.find((s) => s.id === id)?.pts
    return pts?.length ? pts[pts.length - 1].v : null
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-heading text-xl font-bold">{meta.label} <span className="font-sans text-sm font-normal text-muted-foreground">· one line per astronaut · {meta.unit}</span></h2>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          {/* what is plotted: bordered button group, filled when selected */}
          <ToggleGroup size="lg" joined value={key} onChange={setKey} options={[{ value: 'hr', label: 'Heart rate' }, { value: 'spo2', label: 'Blood oxygen' }, { value: 'core', label: 'Body temp.' }]} />
          {/* how far back: light segmented control with a clock */}
          <div className="flex items-center gap-2 text-muted-foreground" role="group" aria-label="Time window">
            <Clock className="size-5" aria-hidden />
            <ToggleGroup size="lg" value={win} onChange={setWin} options={[{ value: '15m', label: '15 min' }, { value: '1h', label: '1 h' }, { value: '6h', label: '6 h' }]} />
          </div>
        </div>
      </div>

      {!model ? (
        <div className="grid min-h-0 flex-1 place-items-center rounded-lg bg-muted text-sm text-muted-foreground">Waiting for data…</div>
      ) : null}
      <div ref={boxRef} className={cn('relative min-h-[200px] flex-1', !model && 'hidden')}>
        {model && <>
          <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} width={W} height={H} className="block" role="img" aria-label={`Crew ${meta.label.toLowerCase()}`}
            style={{ touchAction: 'pan-y' }}
            onPointerDown={onMove} onPointerMove={onMove} onPointerLeave={() => setCursor(null)} onPointerCancel={() => setCursor(null)}>
            {/* normal band + danger zone */}
            <rect x={PADL} y={model.y(Math.min(meta.normal[1], model.hi))} width={PW} height={Math.max(0, model.y(meta.normal[0]) - model.y(Math.min(meta.normal[1], model.hi)))} fill="var(--status-live)" fillOpacity={0.09} />
            {(() => {
              const yc = model.y(meta.crit)
              const [a, b] = meta.dangerBelow ? [yc, PADT + PH] : [PADT, yc]
              return <rect x={PADL} y={a} width={PW} height={Math.max(0, b - a)} fill="var(--status-danger)" fillOpacity={0.08} />
            })()}

            {/* grid + axes */}
            {model.yTicks.map((v) => (
              <g key={v}>
                <line x1={PADL} x2={W - PADR} y1={model.y(v)} y2={model.y(v)} stroke="var(--border)" strokeOpacity={0.7} />
                <text x={PADL - 8} y={model.y(v) + 4} fontSize="12" textAnchor="end" className="fill-muted-foreground">{v.toFixed(meta.dec)}</text>
              </g>
            ))}
            {model.xTicks.map((t) => (
              <g key={t}>
                <line x1={model.x(t)} x2={model.x(t)} y1={PADT} y2={PADT + PH} stroke="var(--border)" strokeOpacity={0.45} />
                <text x={model.x(t)} y={H - 8} fontSize="12" textAnchor="middle" className="fill-muted-foreground">{clock(t, off).slice(0, 5)}</text>
              </g>
            ))}
            <text x={W - PADR} y={H - 8} fontSize="12" fontWeight={600} textAnchor="end" className="fill-foreground">now</text>

            {/* critical threshold */}
            <line x1={PADL} x2={W - PADR} y1={model.y(meta.crit)} y2={model.y(meta.crit)} stroke="var(--status-danger)" strokeDasharray="5 4" />
            <text x={PADL + 6} y={model.y(meta.crit) + (meta.dangerBelow ? 15 : -6)} fontSize="12" className="fill-status-danger-foreground">critical threshold {meta.crit}</text>

            {/* emergencies */}
            {visibleSpans.map((s) => {
              const x0 = model.x(Math.max(s.t0, model.tMin)), x1 = model.x(Math.min(s.t1 ?? model.tMax, model.tMax))
              return (
                <g key={s.id}>
                  <rect x={x0} y={PADT} width={Math.max(2, x1 - x0)} height={PH} fill={s.color} fillOpacity={0.07} />
                  <rect x={x0} y={PADT} width={Math.max(2, x1 - x0)} height={5} fill={s.color} />
                  {s.t0 >= model.tMin && <line x1={x0} x2={x0} y1={PADT} y2={PADT + PH} stroke={s.color} strokeWidth={1.5} strokeDasharray="3 3" />}
                  <title>{s.text}</title>
                </g>
              )
            })}

            {/* lines */}
            {model.series.map((s) => s.pts.length > 0 && (
              <polyline key={s.id} fill="none" stroke={crewIdentity(s.id).color} strokeWidth={focus === s.id ? 3.2 : 2.2} strokeLinejoin="round" strokeLinecap="round"
                opacity={focus && focus !== s.id ? 0.18 : 1} points={s.pts.map((p) => `${model.x(p.t).toFixed(1)},${model.y(p.v).toFixed(1)}`).join(' ')} />
            ))}

            {/* end-of-line labels */}
            {model.tips.map((t) => (
              <g key={t.id} opacity={focus && focus !== t.id ? 0.25 : 1}>
                <circle cx={W - PADR + 8} cy={t.y} r={4.5} fill={crewIdentity(t.id).color} />
                <text x={W - PADR + 18} y={t.y + 5} fontSize="14" fontWeight={600} className="fill-foreground">
                  {crewIdentity(t.id).first} {t.v.toFixed(meta.dec)}
                </text>
              </g>
            ))}

            {/* crosshair */}
            {hover && (
              <g pointerEvents="none">
                <line x1={model.x(hover.t)} x2={model.x(hover.t)} y1={PADT} y2={PADT + PH} stroke="var(--foreground)" strokeOpacity={0.5} />
                {hover.rows.map((r) => <circle key={r.id} cx={model.x(r.t)} cy={model.y(r.v)} r={5} fill={crewIdentity(r.id).color} stroke="var(--card)" strokeWidth={2} />)}
              </g>
            )}
          </svg>

          {hover && (
            <div className="pointer-events-none absolute top-2 z-10 min-w-40 rounded-lg border bg-popover px-3 py-2 text-sm text-popover-foreground shadow-md"
              style={hover.left > 55 ? { right: `${100 - hover.left + 2}%` } : { left: `${hover.left + 2}%` }}>
              <div className="mb-1 font-semibold tabular-nums">{clock(hover.t, off)}</div>
              {hover.rows.map((r) => (
                <div key={r.id} className="flex items-center justify-between gap-4">
                  <span className="flex items-center gap-2"><span className="size-2.5 rounded-full" style={{ background: crewIdentity(r.id).color }} />{crewIdentity(r.id).first}</span>
                  <span className="font-medium tabular-nums">{r.v.toFixed(meta.dec)} {meta.unit}</span>
                </div>
              ))}
              {hover.events.map((s) => (
                <div key={s.id} className="mt-1 flex items-start gap-2 border-t pt-1 text-xs" style={{ color: s.color }}>
                  <span aria-hidden>▲</span><span>{s.text}</span>
                </div>
              ))}
            </div>
          )}
        </>}
      </div>

      {/* pl-28: keeps clear of the corner menu button (bottom left) */}
      <div className="mt-3 flex flex-wrap gap-3 pl-28">
        {ids.map((id) => {
          const v = latest(id)
          return (
            <button key={id} type="button" aria-pressed={focus === id} onClick={() => setFocus(focus === id ? null : id)}
              className={cn('flex h-11 items-center justify-center gap-2 rounded-full border-2 px-5 text-base font-bold text-foreground outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50 active:bg-muted-strong', focus === id && 'bg-muted-strong')}
              style={{ borderColor: crewIdentity(id).color }}>
              {crewIdentity(id).first}
              {v != null && <span className="font-medium tabular-nums text-muted-foreground">{v.toFixed(meta.dec)}</span>}
            </button>
          )
        })}
      </div>
    </div>
  )
})
