import type { VitalsSource } from './contracts'
import { ingestTick, setState } from './store'
import { WebSocketBackend } from './websocket'

const env = import.meta.env as Record<string, string | undefined>
export const BACKEND_URL = env.VITE_ARES_WS_URL ?? 'ws://127.0.0.1:8765'

/** One instance: VitalsSource and command client at once. */
export const backend = new WebSocketBackend({
  url: BACKEND_URL,
  onHello: (h) => setState({ scenario: h.scenario, paused: h.paused, speed: h.speed }),
  onStatus: (s) => setState({ paused: s.paused, speed: s.speed }),
  onConnection: (connected) => setState({ connected }),
})

setState({ url: BACKEND_URL })

export const source: VitalsSource = backend

let stop: (() => void) | null = null
/** Idempotent: starts feeding the store. */
export function startTelemetry() {
  if (!stop) stop = source.subscribe(ingestTick)
  return () => { /* kept alive for the app lifetime (StrictMode double mount) */ }
}
