import { statusText, vitalStatus } from '@/domain/status'
import { fmt0, fmt1 } from '@/domain/units'
import type { NPCState } from '@/telemetry'
import type { Anchors } from './HologramFrame'

interface Callout { label: string; value: string; unit: string; organ: string; side: 'l' | 'r'; dy: number; cls: string }

/** Four callouts, two per side, with guide lines to the organ anchors (data-organ in the hologram). */
export function HologramCallouts({ npc, anchors, width, height }: { npc: NPCState; anchors: Anchors; width: number; height: number }) {
  const v = npc.vitals
  const items: Callout[] = [
    { label: 'Body temperature', value: fmt1(v.core_temp_c), unit: '°C', organ: 'brain', side: 'l', dy: 0, cls: statusText[vitalStatus('core_temp_c', v.core_temp_c)] },
    { label: 'Heart rate', value: fmt0(v.hr), unit: 'bpm', organ: 'heart', side: 'r', dy: 0, cls: statusText[vitalStatus('hr', v.hr, npc.activity)] },
    { label: 'Blood oxygen', value: fmt0(v.spo2), unit: '%', organ: 'lungs', side: 'l', dy: 0, cls: statusText[vitalStatus('spo2', v.spo2)] },
    { label: 'Breathing rate', value: fmt0(v.resp_rate), unit: '/min', organ: 'lungs', side: 'r', dy: 40, cls: statusText[vitalStatus('resp_rate', v.resp_rate)] },
  ]
  // Row of each callout on its side (0 = upper, 1 = lower), as a fraction of the height.
  const SLOT_Y = [0.12, 0.38]
  const next = { l: 0, r: 0 }
  const placed = items.map((c) => ({ ...c, y: SLOT_Y[next[c.side]++] * height }))
  return (
    <>
      <svg aria-hidden className="pointer-events-none absolute inset-0" width={width} height={height}>
        {placed.map((c) => {
          const a = anchors[c.organ]
          if (!a) return null
          const y = c.y + 24
          const x = c.side === 'l' ? 0 : width
          return <polyline key={c.label} points={`${x},${y} ${(x + a.x) / 2},${y} ${a.x},${a.y + c.dy}`} fill="none" stroke="color-mix(in oklab, var(--chart-1) 60%, transparent)" strokeWidth={1} />
        })}
      </svg>
      {placed.map((c) => (
        <dl key={c.label} className="absolute m-0" style={{ top: c.y, [c.side === 'l' ? 'left' : 'right']: 0, textAlign: c.side === 'l' ? 'left' : 'right' }}>
          <dt className="text-xs font-medium text-muted-foreground">{c.label}</dt>
          <dd className={`num m-0 text-5xl leading-none tabular-nums ${c.cls}`}>{c.value}<span className="ml-1 font-sans text-sm font-normal text-muted-foreground">{c.unit}</span></dd>
        </dl>
      ))}
    </>
  )
}
