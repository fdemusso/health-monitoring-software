import { useEffect, useState } from 'react'
import { useWaiting, useWarmup } from '@/telemetry/useTelemetry'
import { cn } from '@/lib/utils'

/** Pointy-top hexagon, centre (100,110), radius `r`; starts at the top and goes clockwise, so the progress stroke fills clockwise. */
const hex = (r: number) => {
  const p = [0, 60, 120, 180, 240, 300].map((deg) => {
    const a = ((deg - 90) * Math.PI) / 180
    return `${(100 + r * Math.cos(a)).toFixed(1)} ${(110 + r * Math.sin(a)).toFixed(1)}`
  })
  return `M${p.join(' L')} Z`
}

/** A heartbeat, drawn left to right; `pathLength` is 1 so the dash animation is independent of its real length. */
const ECG = 'M0 30 H92 l8 -6 l8 6 H134 l6 5 l8 -34 l8 46 l8 -17 H196 l9 -8 l11 8 H300'

/** Time left, from how fast the progress moved since the first report. Null until there is enough to estimate from. */
function secondsLeft(startedAt: number, startProgress: number, progress: number, now: number): number | null {
  const moved = progress - startProgress
  const elapsed = (now - startedAt) / 1000
  if (moved < 0.03 || elapsed < 2) return null
  return Math.max(0, Math.round((elapsed * (1 - progress)) / moved))
}

/**
 * Shown while there is nothing to show yet: from the first paint until the backend answers (loading, port not open), and while it
 * runs the simulation ahead (`ares3 serve --warmup-h`). Covers the whole app (which is `inert` meanwhile, see Shell) and fades out when the backend says `ready`.
 */
export function WarmupScreen() {
  const w = useWarmup()
  const waiting = useWaiting()
  const [now, setNow] = useState(() => Date.now())
  const active = w !== null
  useEffect(() => {
    if (!active) return
    const i = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(i)
  }, [active])
  if (!w && !waiting) return null

  const progress = w?.progress ?? 0
  const pct = Math.round(progress * 100)
  const left = w ? secondsLeft(w.startedAt, w.startProgress, progress, now) : null
  return (
    <div
      className={cn('fixed inset-0 z-[90] flex flex-col items-center justify-center gap-8 bg-background px-10 text-center', w?.finishing ? 'animate-out fade-out-0 fill-mode-forwards duration-500' : 'animate-in fade-in-0 duration-500')}
      style={{ backgroundImage: 'radial-gradient(900px 480px at 50% 30%, color-mix(in oklab, var(--chart-1) 14%, transparent), transparent 70%)' }}
    >
      <div role="progressbar" aria-label="Station warm-up" aria-valuemin={0} aria-valuemax={100} aria-valuenow={w ? pct : undefined} className="relative size-56">
        <svg viewBox="0 0 200 220" className="size-full" aria-hidden>
          <path d={hex(90)} fill="none" stroke="var(--border)" strokeWidth={3} strokeLinejoin="round" />
          <path d={hex(90)} pathLength={1} fill="none" stroke="var(--chart-1)" strokeWidth={4} strokeLinecap="round" strokeLinejoin="round"
            strokeDasharray={1} strokeDashoffset={1 - progress} className="transition-[stroke-dashoffset] duration-500 ease-linear" />
          <path d={hex(70)} fill="none" stroke="var(--chart-1)" strokeOpacity={0.35} strokeWidth={1.5} className="anim-spin-slow" />
          <path d={hex(50)} fill="none" stroke="var(--chart-1)" strokeOpacity={0.2} strokeWidth={1.5} className="anim-spin-slow-rev" />
        </svg>
        <div className="num absolute inset-0 grid place-items-center text-6xl">
          {w ? <span>{pct}<span className="ml-0.5 font-sans text-xl font-normal text-muted-foreground">%</span></span> : <span className="text-muted-foreground">…</span>}
        </div>
      </div>

      <svg viewBox="0 0 300 60" className="h-12 w-72" aria-hidden>
        <path d={ECG} pathLength={1} fill="none" stroke="var(--border)" strokeWidth={2} strokeLinejoin="round" />
        <path d={ECG} pathLength={1} fill="none" stroke="var(--chart-1)" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" className="anim-ecg" />
      </svg>

      <div className="w-80 space-y-2">
        <h1 className="text-3xl">Preparing the station</h1>
        <p className="h-6 text-base tabular-nums text-muted-foreground">{!w ? 'Connecting to the station…' : left == null ? 'Estimating time left…' : left < 2 ? 'Almost ready' : `About ${left} s left`}</p>
      </div>
      {/* screen readers: one announcement per 10 %, not one per frame */}
      <p role="status" className="sr-only">Preparing the station, {Math.floor(pct / 10) * 10}%</p>
    </div>
  )
}
