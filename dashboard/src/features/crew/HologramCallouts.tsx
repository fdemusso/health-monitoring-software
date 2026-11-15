import { statusText, vitalStatus } from '@/domain/status'
import { fmt0, fmt1 } from '@/domain/units'
import type { NPCState } from '@/telemetry'
import type { Anchors } from './HologramFrame'

interface Callout { label: string; value: string; unit: string; organ: string; side: 'l' | 'r'; dy: number; cls: string }

/** Four callouts, two per side, with guide lines to the organ anchors (data-organ in the hologram). */
export function HologramCallouts({ npc, anchors, width, height }: { npc: NPCState; anchors: Anchors; width: number; height: number }) {
  const v = npc.vitals
  const items: Callout[] = [
    { label: 'Temp. core', value: fmt1(v.core_temp_c), unit: '°C', organ: 'brain', side: 'l', dy: 0, cls: statusText[vitalStatus('core_temp_c', v.core_temp_c)] },
    { label: 'Freq. cardiaca', value: fmt0(v.hr), unit: 'bpm', organ: 'heart', side: 'r', dy: 0, cls: statusText[vitalStatus('hr', v.hr, npc.activity)] },
    { label: 'SpO₂', value: fmt0(v.spo2), unit: '%', organ: 'lungs', side: 'l', dy: 0, cls: statusText[vitalStatus('spo2', v.spo2)] },
    { label: 'Freq. respiro', value: fmt0(v.resp_rate), unit: '/min', organ: 'lungs', side: 'r', dy: 40, cls: statusText[vitalStatus('resp_rate', v.resp_rate)] },
  ]
  const slotY: Record<string, number> = { 'l0': 0.12, 'l1': 0.38, 'r0': 0.12, 'r1': 0.38 }
  let li = 0, ri = 0
  return (
    <>
      <svg aria-hidden className="pointer-events-none absolute inset-0" width={width} height={height}>
        {items.map((c, i) => {
          const a = anchors[c.organ]
          if (!a) return null
          const slot = c.side === 'l' ? li++ : ri++
          const y = slotY[`${c.side}${slot}`] * height + 24
          const x = c.side === 'l' ? 0 : width
          return <polyline key={i} points={`${x},${y} ${(x + a.x) / 2},${y} ${a.x},${a.y + c.dy}`} fill="none" stroke="rgb(143 211 255 / .5)" strokeWidth={1} />
        })}
      </svg>
      {(() => { li = 0; ri = 0; return null })()}
      {items.map((c, i) => {
        const slot = c.side === 'l' ? li++ : ri++
        const y = slotY[`${c.side}${slot}`] * height
        return (
          <div key={i} className="absolute" style={{ top: y, [c.side === 'l' ? 'left' : 'right']: 0, textAlign: c.side === 'l' ? 'left' : 'right' }}>
            <div className="text-[11px] uppercase tracking-widest text-muted-foreground">{c.label}</div>
            <div className={`num text-[40px] leading-none tabular-nums ${c.cls}`}>{c.value}<span className="ml-1 text-sm text-muted-foreground">{c.unit}</span></div>
          </div>
        )
      })}
    </>
  )
}
