import { Tablet } from 'lucide-react'
import { globalStatus } from '@/domain/status'
import { useCrewList, useEmergencies } from '@/telemetry/useTelemetry'
import { useUi } from './ui-context'

/** Red breathing edge while a critical emergency is open. Decorative. */
export function Vignette() {
  const crew = useCrewList()
  const emergencies = useEmergencies()
  if (globalStatus(crew, emergencies) !== 'crit') return null
  return <div aria-hidden className="anim-breathe pointer-events-none fixed inset-0 z-[1]" />
}

/** Short message at the bottom of the screen (`useUi().showToast`). */
export function Toast() {
  const { toast } = useUi()
  return toast ? <p role="status" className="fixed bottom-24 left-1/2 z-40 -translate-x-1/2 rounded-full border border-border bg-card px-5 py-2 text-sm font-medium animate-in fade-in-0 duration-(--duration-enter)">{toast}</p> : null
}

/** Portrait screens only get this notice: the layout is built for landscape. Pure CSS (the `portrait:` variant), so the app
 *  underneath stays mounted and connected and nothing is lost when the device is rotated back. */
export function RotateNotice() {
  return (
    <div role="alert" className="fixed inset-0 z-[100] hidden flex-col items-center justify-center gap-6 bg-background px-10 text-center portrait:flex">
      <Tablet className="anim-rotate-hint size-20 text-muted-foreground" strokeWidth={1.25} aria-hidden />
      <h1 className="text-3xl">Rotate your device</h1>
      <p className="max-w-sm text-lg text-muted-foreground">ARES 3 works in landscape. Turn the screen sideways to continue.</p>
    </div>
  )
}
