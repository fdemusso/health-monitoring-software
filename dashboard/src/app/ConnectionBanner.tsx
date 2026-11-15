import { useEffect, useState } from 'react'
import { useBackendStatus } from '@/telemetry/useTelemetry'

export function ConnectionBanner() {
  const { connected, url, lastTickAt, paused } = useBackendStatus()
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => { const i = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(i) }, [])
  const stale = connected && !paused && lastTickAt > 0 && now - lastTickAt > 5000
  if (connected && !stale) return null
  return (
    <div role="status" className="z-[3] border-b border-border bg-status-warning-soft px-7 py-1.5 text-center text-xs text-status-warning-foreground">
      {!connected
        ? <>Backend non raggiungibile (<code className="rounded-control bg-muted px-1.5 font-mono text-xs">{url}</code>) — avvia <code className="rounded-control bg-muted px-1.5 font-mono text-xs">uv run ares3 serve scenarios/events/debug_station.yaml</code></>
        : <>Dati non aggiornati da {Math.round((now - lastTickAt) / 1000)} s</>}
    </div>
  )
}
