import { StatusDot } from '@/components/StatusDot'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { SimulationTick } from '@/telemetry'
import { alertRows } from './alertRows'

export function AlertList({ tick }: { tick: SimulationTick }) {
  const rows = alertRows(tick)
  return (
    <section aria-label="Active alerts" className="flex min-h-[11rem] flex-1 basis-0 flex-col">
      <h2 className="mb-2 flex shrink-0 items-center gap-2 font-heading text-xl font-bold">
        Active alerts
        {rows.length === 0 ? <span className="font-sans text-sm font-normal text-muted-foreground">· none</span> : <span className="font-sans text-sm font-normal text-muted-foreground">· {rows.length}</span>}
      </h2>
      {rows.length > 0 && (
        <ScrollArea className="min-h-0">
          <ul className="space-y-2 pr-3">
            {rows.map((r) => (
              <li key={r.key} className="flex items-start gap-3 rounded-lg border border-border bg-card p-3">
                <StatusDot status={r.status} className="mt-2" />
                <div className="min-w-0"><div className="flex items-center gap-2">{r.chip}<span className="truncate text-sm">{r.text}</span></div><div className="mt-0.5 text-xs text-muted-foreground">{r.sub}</div></div>
              </li>
            ))}
          </ul>
        </ScrollArea>
      )}
    </section>
  )
}
