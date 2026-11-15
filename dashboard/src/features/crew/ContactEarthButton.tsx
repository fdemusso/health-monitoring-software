import { Check } from 'lucide-react'
import { useEffect, useSyncExternalStore } from 'react'
import { useUi } from '@/app/ui-context'
import { Button } from '@/components/ui/button'
import { useCommands, useEmergencies } from '@/telemetry/useTelemetry'

/** One mayday per incident, shared by every Contact Earth button on screen: once pressed they all stay disabled until no emergency is open. */
let sent = false
const listeners = new Set<() => void>()
const setSent = (v: boolean) => { if (sent !== v) { sent = v; listeners.forEach((l) => l()) } }
const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l) } }

/** Seconds (real time) after the mayday when Earth "has dealt with it": the simulation goes back to a normal station. */
const EARTH_RESOLVES_S = 20

/** Automatic mayday to Earth: a plain button, no panel. The link is not simulated; the press is acknowledged, the button stays disabled and a little later the station is back to normal. */
export function ContactEarthButton({ size }: { size?: 'lg' }) {
  const ui = useUi()
  const cmd = useCommands()
  const done = useSyncExternalStore(subscribe, () => sent)
  const open = useEmergencies().some((e) => e.state !== 'cleared')
  useEffect(() => { if (!open) setSent(false) }, [open])
  return (
    <Button size={size} variant="outline" disabled={done} onClick={() => {
      setSent(true)
      ui.showToast('Mayday sent to Earth')
      window.setTimeout(() => { void cmd.reset(); ui.showToast('Earth has dealt with it: the station is back to normal') }, EARTH_RESOLVES_S * 1000)
    }}>
      {done ? <><Check aria-hidden /> Earth notified</> : 'Contact Earth'}
    </Button>
  )
}
