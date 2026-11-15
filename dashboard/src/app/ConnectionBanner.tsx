import { useEffect, useState } from 'react'
import { useBackendStatus } from '@/telemetry/useTelemetry'

export function ConnectionBanner() {
  const { connected, url, lastTickAt, paused } = useBackendStatus()
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => { const i = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(i) }, [])
  const stale = connected && !paused && lastTickAt > 0 && now - lastTickAt > 5000
  if (connected && !stale) return null
  return (
    <div role="status" className="z-[3] border-b border-warn/40 bg-warn/10 px-7 py-1.5 text-center text-xs text-warn">
      {!connected
        ? <>Backend non raggiungibile (<span className="font-mono">{url}</span>) — avvia <span className="font-mono">uv run ares3 serve scenarios/events/debug_station.yaml</span></>
        : <>Dati non aggiornati da {Math.round((now - lastTickAt) / 1000)} s</>}
    </div>
  )
}
