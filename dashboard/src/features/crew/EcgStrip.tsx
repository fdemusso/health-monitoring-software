import { useEffect, useRef } from 'react'
import { ECG_FS, EcgSynth, type EcgInput } from '@/domain/ecg'
import type { NPCState } from '@/telemetry'

/** Seconds on screen (25 mm/s on a 150 mm strip) and the blank gap in front of the writing head. */
const WINDOW_S = 6
const GAP_S = 0.25
/** The trace spans these millivolts top to bottom. */
const MV_TOP = 1.4
const MV_BOTTOM = -0.6

/** What the wearable reads from the simulation at this moment. */
const inputOf = (npc: NPCState): EcgInput => ({
  hr: npc.vitals.hr, af: (npc.vitals.rhythm ?? 0) >= 0.5, hrvMs: npc.vitals.hrv_rmssd ?? 40, respPerMin: npc.vitals.resp_rate ?? 14, met: npc.met,
})

/**
 * One-lead ECG written left to right like a bedside monitor, in REAL time (not simulation time): the shape comes from the
 * simulated heart rate, variability and rhythm (domain/ecg.ts). Drawn on a canvas from a requestAnimationFrame loop, outside React:
 * the component re-renders with every tick, the loop only reads the latest vitals from a ref. Stops while the tab is hidden or a panel is dragged.
 */
export function EcgStrip({ npc, color = 'var(--status-live)' }: { npc: NPCState; color?: string }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const latest = useRef(npc)
  useEffect(() => { latest.current = npc })
  const who = `${npc.id}|${npc.sex}|${npc.age_y}|${npc.height_cm}|${npc.body_mass_kg}`

  useEffect(() => {
    const el = canvas.current
    const g = el?.getContext('2d')
    if (!el || !g) return
    const synth = new EcgSynth(latest.current, () => inputOf(latest.current))
    const n = Math.round(WINDOW_S * ECG_FS)
    const buf = new Float32Array(n).fill(NaN)
    let head = 0, acc = 0, last = performance.now(), raf = 0, frame = 0
    let ink = '', grid = ''

    const size = () => {
      const r = el.getBoundingClientRect(), d = window.devicePixelRatio || 1
      el.width = Math.round(r.width * d); el.height = Math.round(r.height * d)
      g.setTransform(d, 0, 0, d, 0, 0)
    }
    const ro = new ResizeObserver(size)
    ro.observe(el)
    size()

    const draw = () => {
      const W = el.clientWidth, H = el.clientHeight
      const y = (mv: number) => ((MV_TOP - mv) / (MV_TOP - MV_BOTTOM)) * H
      g.clearRect(0, 0, W, H)
      // paper: a line every 0.2 s (5 mm) and every 0.5 mV
      g.strokeStyle = grid; g.lineWidth = 1; g.beginPath()
      for (let s = 0; s <= WINDOW_S; s += 0.2) { const x = Math.round((s / WINDOW_S) * W) + 0.5; g.moveTo(x, 0); g.lineTo(x, H) }
      for (let mv = MV_BOTTOM; mv <= MV_TOP + 1e-6; mv += 0.5) { const yy = Math.round(y(mv)) + 0.5; g.moveTo(0, yy); g.lineTo(W, yy) }
      g.stroke()
      g.strokeStyle = ink; g.lineWidth = 1.8; g.lineJoin = 'round'; g.beginPath()
      let pen = false
      for (let k = 0; k < n; k++) {
        const v = buf[k]
        const gap = (k - head + n) % n < GAP_S * ECG_FS // just ahead of the head: the old trace is erased
        if (Number.isNaN(v) || gap || k === head) { pen = false; continue }
        const x = (k / n) * W
        if (pen) g.lineTo(x, y(v)); else { g.moveTo(x, y(v)); pen = true }
      }
      g.stroke()
    }

    const loop = (now: number) => {
      raf = requestAnimationFrame(loop)
      const dt = Math.min((now - last) / 1000, 0.1)
      last = now
      if (document.hidden || document.documentElement.hasAttribute('data-dragging')) return
      if (frame++ % 60 === 0) { // the theme can change: read the colours now and then
        const cs = getComputedStyle(el)
        ink = color.startsWith('var(') ? cs.getPropertyValue(color.slice(4, -1)).trim() || '#2e9e6b' : color
        grid = `color-mix(in oklab, ${cs.getPropertyValue('--foreground').trim() || 'currentColor'} 9%, transparent)`
      }
      acc += dt * ECG_FS
      while (acc >= 1) { buf[head] = synth.next(1 / ECG_FS); head = (head + 1) % n; acc -= 1 }
      draw()
    }
    raf = requestAnimationFrame(loop)
    return () => { cancelAnimationFrame(raf); ro.disconnect() }
  }, [who, color])

  return <canvas ref={canvas} role="img" aria-label={`Simulated ECG, real time, of ${npc.id}, ${Math.round(npc.vitals.hr)} beats per minute`} className="block h-28 w-full rounded-control bg-muted/40" />
}
