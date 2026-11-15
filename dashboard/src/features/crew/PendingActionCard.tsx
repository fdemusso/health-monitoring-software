import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { fmtClock } from '@/domain/units'
import type { PendingAction } from '@/telemetry'
import { useCommands } from '@/telemetry/useTelemetry'

const KIND: Record<string, string> = { extinguish: 'Estintore', actuator: 'Attuatore', hatch: 'Portello', announce: 'Annuncio', ventilation: 'Ventilazione' }

export function PendingActionCard({ pa, tSim }: { pa: PendingAction; tSim: number }) {
  const cmd = useCommands()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const a = pa.action
  const run = async (fn: () => ReturnType<typeof cmd.approve>) => {
    setBusy(true); setError(null)
    const r = await fn()
    if (!r.ok) { setError(r.error ?? 'rifiutato'); setBusy(false) }
    // On success the card disappears when the next tick no longer lists it.
  }
  return (
    <div className="rounded-lg border border-border bg-muted p-4">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="lbl">{KIND[a.kind] ?? a.kind}</span>
        <span className="text-sm font-medium tabular-nums">{fmtClock(pa.deadline_s - tSim)}</span>
      </div>
      <p className="text-base">{a.reason || `${a.command} ${a.target}`}</p>
      <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>Se nessuno risponde: {pa.on_timeout === 'execute' ? 'verrà eseguita' : 'verrà scartata'}</span>
        {a.reversible && <Badge>Reversibile</Badge>}
      </div>
      <div className="mt-3 flex gap-2">
        <Button size="lg" className="flex-1" disabled={busy} onClick={() => run(() => cmd.approve(a.id))}>Approva</Button>
        <Button size="lg" className="flex-1" variant="outline" disabled={busy} onClick={() => run(() => cmd.reject(a.id))}>Rifiuta</Button>
      </div>
      {error && <p className="mt-2 text-xs text-status-danger-foreground">{error}</p>}
    </div>
  )
}
