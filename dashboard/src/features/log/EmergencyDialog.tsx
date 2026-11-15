import { useUi } from '@/app/ui-context'
import { Dialog } from '@/components/ui/dialog'
import { ResponsePanel } from '@/features/crew/ResponsePanel'
import { useTick } from '@/telemetry/useTelemetry'

export function EmergencyDialog() {
  const { sheetEmergency, setSheetEmergency } = useUi()
  const tick = useTick()
  const e = tick?.emergencies.find((x) => x.id === sheetEmergency) ?? null
  return (
    <Dialog open={!!sheetEmergency && !!tick} onClose={() => setSheetEmergency(null)} title="Emergency response" width={640}>
      {tick && e && <ResponsePanel tick={tick} emergency={e} />}
      {tick && !e && <p className="text-sm text-muted-foreground">The emergency is no longer active.</p>}
    </Dialog>
  )
}
