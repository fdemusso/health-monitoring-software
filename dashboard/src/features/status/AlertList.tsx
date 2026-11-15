import { StatusDot } from '@/components/StatusDot'
import { useUi } from '@/app/ui-context'
import { Button } from '@/components/ui/button'
import type { SimulationTick } from '@/telemetry'
import { alertRows } from './alertRows'

export function AlertList({ tick }: { tick: SimulationTick }) {
  const ui = useUi()
  const rows = alertRows(tick)
  return (
    <div>
      <h2 className="mb-2 flex items-center gap-2 font-heading text-xl font-bold">
        Active alerts
        {rows.length === 0 && <span className="font-sans text-sm font-normal text-muted-foreground">· none</span>}
      </h2>
      {rows.length === 0 ? null : (
        <ul className="space-y-2">
          {rows.slice(0, 4).map((r) => (
            <li key={r.key} className="flex items-start gap-3 rounded-lg border border-border bg-card p-3">
              <StatusDot status={r.status} className="mt-2" />
              <div className="min-w-0"><div className="flex items-center gap-2">{r.chip}<span className="truncate text-sm">{r.text}</span></div><div className="mt-0.5 text-xs text-muted-foreground">{r.sub}</div></div>
            </li>
          ))}
        </ul>
      )}
      {rows.length > 4 && <Button variant="outline" className="mt-2" onClick={() => ui.setAlertsOpen(true)}>All alerts ({rows.length})</Button>}
    </div>
  )
}
