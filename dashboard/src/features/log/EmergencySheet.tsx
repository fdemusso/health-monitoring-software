import { useUi } from '@/app/ui-context'
import { Sheet } from '@/components/ui/sheet'
import { ResponsePanel } from '@/features/crew/ResponsePanel'
import { useTick } from '@/telemetry/useTelemetry'

export function EmergencySheet() {
  const { sheetEmergency, setSheetEmergency } = useUi()
  const tick = useTick()
  const e = tick?.emergencies.find((x) => x.id === sheetEmergency) ?? null
  return (
    <Sheet open={!!sheetEmergency && !!tick} onClose={() => setSheetEmergency(null)} title="Risposta all’emergenza" width={420}>
      {tick && e && <ResponsePanel tick={tick} emergency={e} />}
      {tick && !e && <p className="text-sm text-muted-foreground">L’emergenza non è più attiva.</p>}
    </Sheet>
  )
}
