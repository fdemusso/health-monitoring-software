import { useUi } from '@/app/ui-context'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { StatusDot } from '@/components/StatusDot'
import { useTick } from '@/telemetry/useTelemetry'
import { alertRows } from './alertRows'

/** Alarm centre: every active emergency and alarm, each with a way to its response. */
export function AlertsDialog() {
  const ui = useUi()
  const tick = useTick()
  const rows = tick ? alertRows(tick) : []
  const open = (subject: string | null | undefined, id: string) => {
    ui.setAlertsOpen(false)
    if (subject) ui.openCrew(subject)
    else ui.setSheetEmergency(id)
  }
  return (
    <Dialog open={ui.alertsOpen} onClose={() => ui.setAlertsOpen(false)} title="Alarms" width={720}>
      {rows.length === 0 ? <p className="text-sm text-muted-foreground">No active alerts.</p> : (
        <ul className="space-y-2">
          {rows.map((r) => (
            <li key={r.key} className="flex items-center gap-3 rounded-lg border border-border bg-card p-3">
              <StatusDot status={r.status} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">{r.chip}<span className="truncate text-sm font-medium">{r.text}</span></div>
                <div className="mt-0.5 text-xs text-muted-foreground">{r.sub}</div>
              </div>
              {r.emergency && <Button variant="outline" onClick={() => open(r.emergency?.subject, (r.emergency as { id: string }).id)}>Open response</Button>}
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  )
}
