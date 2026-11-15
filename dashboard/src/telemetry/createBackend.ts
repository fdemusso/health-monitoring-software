import type { VitalsSource } from './contracts'
import { ingestHistory, ingestTick, setState } from './store'
import { WebSocketBackend } from './websocket'

const env = import.meta.env as Record<string, string | undefined>
export const BACKEND_URL = env.VITE_ARES_WS_URL ?? 'ws://127.0.0.1:8765'

/** The operator token comes from the page address (`https://ares.example/#token=...`): a fragment never reaches a server or a log.
 *  Without it the backend treats this page as a viewer (it receives everything, its commands are refused). Kept out of BACKEND_URL,
 *  which the UI shows. */
const token = new URLSearchParams(window.location.hash.slice(1)).get('token')
const socketUrl = token ? `${BACKEND_URL.replace(/\/$/, '')}/?token=${encodeURIComponent(token)}` : BACKEND_URL

/** One instance: VitalsSource and command client at once. */
export const backend = new WebSocketBackend({
  url: socketUrl,
  onHello: (h) => setState({ scenario: h.scenario, paused: h.paused, speed: h.speed }),
  onHistory: ingestHistory,
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
