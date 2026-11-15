import { useUi } from '@/app/ui-context'
import { Sheet } from '@/components/ui/sheet'
import { eventFamily, eventLabel } from '@/domain/emergencyText'
import { fmtHms } from '@/domain/units'
import { cn } from '@/lib/utils'
import { useEventLog } from '@/telemetry/useTelemetry'

export function EventLogSheet() {
  const { logOpen, setLogOpen } = useUi()
  const log = useEventLog()
  const rows = [...log].reverse()
  return (
    <Sheet open={logOpen} onClose={() => setLogOpen(false)} title="Storico eventi">
      {rows.length === 0 ? <p className="text-sm text-muted-foreground">Nessun evento del monitor.</p> : (
        <ul className="space-y-2">
          {rows.map((e, i) => {
            const fam = eventFamily(e.kind)
            return (
              <li key={`${e.t_s}-${e.kind}-${i}`} className="rounded-lg border border-border bg-card p-3">
                <div className="flex items-center justify-between text-xs">
                  <span className={cn('font-medium', fam === 'emergency' ? 'text-status-danger-foreground' : fam === 'action' ? 'text-foreground' : 'text-muted-foreground')}>{eventLabel(e.kind)}</span>
                  <span className="tabular-nums text-muted-foreground">{fmtHms(e.t_s)}</span>
                </div>
                <p className="mt-1 text-sm">{e.message}</p>
                {e.by && <p className="mt-0.5 text-xs text-muted-foreground">da {e.by}</p>}
              </li>
            )
          })}
        </ul>
      )}
    </Sheet>
  )
}
