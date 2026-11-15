import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { emergencyTitle } from '@/domain/emergencyText'
import { fmtClock } from '@/domain/units'
import { useCommands, useTick } from '@/telemetry/useTelemetry'

/**
 * Once the whole crew is aboard the lifeboat the scenario is over: a screen says what happened and "Continue" restarts the simulation
 * from a normal station. Nothing is shown while at least one person is still on the station.
 */
export function EvacuationScreen() {
  const tick = useTick()
  const cmd = useCommands()
  const [busy, setBusy] = useState(false)
  const crew = tick ? Object.values(tick.npcs) : []
  const aboard = crew.length > 0 && crew.every((n) => n.module_id.toLowerCase() === 'lifeboat')
  const open = tick ? tick.emergencies.filter((e) => e.state !== 'cleared').map(emergencyTitle) : []
  // what was wrong just before the crew left: the emergencies may be re-grouped once they are aboard
  const [before, setBefore] = useState<string[]>([])
  if (!aboard && open.join('|') !== before.join('|')) setBefore(open)
  if (!tick || !aboard) return null
  const what = open.length ? open : before
  return (
    <div role="alertdialog" aria-modal aria-labelledby="evac-title" className="fixed inset-0 z-[60] grid place-items-center bg-scrim p-6">
      <div className="w-full max-w-xl rounded-lg border-2 border-status-danger bg-popover p-7 text-popover-foreground shadow-2xl">
        <div className="lbl text-status-danger-foreground">Evacuation complete</div>
        <h2 id="evac-title" className="mt-1 font-heading text-4xl font-bold">The crew left the station</h2>
        <p className="mt-3 text-base">All {crew.length} crew members are aboard the lifeboat and its hatches are sealed. Mission time {fmtClock(tick.t_sim_s)}.</p>
        {what.length > 0 && (
          <div className="mt-4">
            <div className="lbl mb-1">What happened</div>
            <ul className="list-disc space-y-1 pl-5 text-sm">{[...new Set(what)].slice(0, 5).map((w) => <li key={w}>{w}</li>)}</ul>
          </div>
        )}
        <p className="mt-4 text-sm text-muted-foreground">Continue restarts the simulation from a normal station.</p>
        <Button size="lg" className="mt-5 w-full" disabled={busy} onClick={async () => { setBusy(true); await cmd.reset(); setBusy(false) }}>Continue</Button>
      </div>
    </div>
  )
}
