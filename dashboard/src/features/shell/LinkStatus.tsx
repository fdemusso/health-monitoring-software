import { useBackendStatus, useTick } from '@/telemetry/useTelemetry'
import { cn } from '@/lib/utils'

function met(day: number, h: number) {
  const hh = Math.floor(h), mm = Math.floor((h - hh) * 60)
  return `MET ${String(day).padStart(2, '0')}:${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`
}

export function LinkStatus() {
  const { connected, paused, speed } = useBackendStatus()
  const tick = useTick()
  return (
    <div className="flex items-center gap-3.5 text-xs text-muted-foreground">
      {tick && <span className="font-mono tabular-nums">{met(tick.day, tick.time_of_day_h)}</span>}
      <span className="font-mono">{paused ? 'in pausa' : `×${speed}`}</span>
      <span className="flex items-center gap-1.5">
        <span className={cn('size-2 rounded-full', connected ? 'bg-ok' : 'bg-crit')} />
        {connected ? 'collegato' : 'scollegato'}
      </span>
    </div>
  )
}
