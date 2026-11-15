import { useBackendStatus, useTick } from '@/telemetry/useTelemetry'
import { StatusBadge } from '@/components/ui/status-badge'
import { ThemeToggle } from './ThemeToggle'

function met(day: number, h: number) {
  const hh = Math.floor(h), mm = Math.floor((h - hh) * 60)
  return `MET ${String(day).padStart(2, '0')}:${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`
}

export function LinkStatus() {
  const { connected, paused, speed } = useBackendStatus()
  const tick = useTick()
  return (
    <div className="flex items-center gap-3 text-sm text-muted-foreground">
      {tick && <span className="tabular-nums">{met(tick.day, tick.time_of_day_h)}</span>}
      <span className="tabular-nums">{paused ? 'paused' : `×${speed}`}</span>
      <StatusBadge status={connected ? 'ok' : 'crit'}>{connected ? 'Connected' : 'Disconnected'}</StatusBadge>
      <ThemeToggle />
    </div>
  )
}
