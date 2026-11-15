import { useUi } from '@/app/ui-context'
import { Dialog } from '@/components/ui/dialog'
import { ResponsePanel } from '@/features/crew/ResponsePanel'
import { useTick } from '@/telemetry/useTelemetry'

export function EmergencyDialog() {
  const { sheetEmergency, setSheetEmergency } = useUi()
  const tick = useTick()
  const e = tick?.emergencies.find((x) => x.id === sheetEmergency) ?? null
  return (
    <Dialog open={!!sheetEmergency && !!tick} onClose={() => setSheetEmergency(null)} title="Risposta all’emergenza" width={640}>
      {tick && e && <ResponsePanel tick={tick} emergency={e} />}
      {tick && !e && <p className="text-sm text-muted-foreground">L’emergenza non è più attiva.</p>}
    </Dialog>
  )
}
