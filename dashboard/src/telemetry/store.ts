import { pio2Mmhg, ppco2Mmhg, rhPercent } from '@/domain/units'
import type { WarmupProgress } from './websocket'
import type { HistorySample, MonitorEvent, SimulationTick } from './types'

/** History sampling period, simulated seconds. */
const SAMPLE_S = 60
const MAX_SAMPLES = 360 // 6 h
const MAX_EVENTS = 200
/** Length of the warm-up screen's exit animation (keep in sync with `duration-500` in WarmupScreen). */
const WARMUP_FADE_MS = 500

export interface CrewSample { t: number; hr?: number; spo2?: number; resp?: number; core?: number; cohb?: number }
export interface ModuleSample { t: number; temp: number; rh: number; pio2: number; ppco2: number; pressure: number; co: number }

/** The server is running the simulation ahead before going live (`--warmup-h`). */
interface WarmupState {
  /** 0..1 */
  progress: number
  simS: number
  totalS: number
  /** Wall-clock ms and progress at the first report, for the time-left estimate. */
  startedAt: number
  startProgress: number
  /** `ready` arrived: the screen fades out, then the state goes back to null. */
  finishing: boolean
}

export interface TelemetryState {
  tick: SimulationTick | null
  /** Wall-clock ms of the last received tick. */
  lastTickAt: number
  connected: boolean
  warming: WarmupState | null
  paused: boolean
  speed: number
  scenario: string | null
  url: string
  crewHistory: Record<string, CrewSample[]>
  moduleHistory: Record<string, ModuleSample[]>
  eventLog: MonitorEvent[]
  commandError: string | null
}

let state: TelemetryState = {
  tick: null, lastTickAt: 0, connected: false, warming: null, paused: false, speed: 0, scenario: null, url: '',
  crewHistory: {}, moduleHistory: {}, eventLog: [], commandError: null,
}
const listeners = new Set<() => void>()
let lastSampleT = -Infinity

export const getState = () => state
export function subscribe(l: () => void) {
  listeners.add(l)
  return () => { listeners.delete(l) }
}
export function setState(patch: Partial<TelemetryState>) {
  state = { ...state, ...patch }
  for (const l of listeners) l()
}

const eventKey = (e: MonitorEvent) => `${e.t_s}|${e.kind}|${e.emergency_id}|${e.action_id}`

type Snapshot = Pick<SimulationTick, 't_sim_s' | 'npcs' | 'modules'>

/** The two histories with one more sample taken from ``snap`` (a live tick or a point of the backend's history). */
function addSample(crewHistory: Record<string, CrewSample[]>, moduleHistory: Record<string, ModuleSample[]>, snap: Snapshot) {
  const ch: Record<string, CrewSample[]> = { ...crewHistory }
  for (const [id, n] of Object.entries(snap.npcs)) {
    const s: CrewSample = {
      t: snap.t_sim_s, hr: n.vitals.hr, spo2: n.vitals.spo2, resp: n.vitals.resp_rate,
      core: n.vitals.core_temp_c, cohb: n.vitals.cohb_pct,
    }
    ch[id] = [...(ch[id] ?? []), s].slice(-MAX_SAMPLES)
  }
  const mh: Record<string, ModuleSample[]> = { ...moduleHistory }
  for (const [id, m] of Object.entries(snap.modules)) {
    const s: ModuleSample = {
      t: snap.t_sim_s, temp: m.temperature_c, rh: rhPercent(m), pio2: pio2Mmhg(m),
      ppco2: ppco2Mmhg(m), pressure: m.pressure_kpa, co: m.co_ppm,
    }
    mh[id] = [...(mh[id] ?? []), s].slice(-MAX_SAMPLES)
  }
  return { ch, mh }
}

/** The history the backend sends once after `hello`: replaces whatever was gathered so far (a reconnection starts from it too). */
export function ingestHistory(samples: HistorySample[]) {
  let ch: Record<string, CrewSample[]> = {}
  let mh: Record<string, ModuleSample[]> = {}
  for (const snap of samples) ({ ch, mh } = addSample(ch, mh, snap))
  if (samples.length) lastSampleT = samples[samples.length - 1].t_sim_s
  setState({ crewHistory: ch, moduleHistory: mh })
}

export function ingestWarming(w: WarmupProgress) {
  const prev = state.warming
  setState({ warming: { progress: w.progress, simS: w.sim_s, totalS: w.total_s, startedAt: prev?.startedAt ?? Date.now(), startProgress: prev?.startProgress ?? w.progress, finishing: false } })
}

/** Warm-up over: lets the screen fade out (`finishing`), then removes it. */
export function endWarming() {
  if (!state.warming || state.warming.finishing) return
  setState({ warming: { ...state.warming, progress: 1, finishing: true } })
  setTimeout(() => setState({ warming: null }), WARMUP_FADE_MS)
}

export function ingestTick(tick: SimulationTick) {
  const patch: Partial<TelemetryState> = { tick, lastTickAt: Date.now() }
  let { crewHistory, moduleHistory } = state

  // Simulation reset (time went backwards): drop history.
  if (state.tick && tick.t_sim_s < state.tick.t_sim_s) {
    crewHistory = {}; moduleHistory = {}; lastSampleT = -Infinity
    patch.crewHistory = crewHistory; patch.moduleHistory = moduleHistory; patch.eventLog = []
  }

  if (tick.t_sim_s - lastSampleT >= SAMPLE_S) {
    lastSampleT = tick.t_sim_s
    const { ch, mh } = addSample(crewHistory, moduleHistory, tick)
    patch.crewHistory = ch; patch.moduleHistory = mh
  }

  if (tick.monitor_events?.length) {
    const seen = new Set(state.eventLog.map(eventKey))
    const fresh = tick.monitor_events.filter((e) => !seen.has(eventKey(e)))
    if (fresh.length) patch.eventLog = [...(patch.eventLog ?? state.eventLog), ...fresh].slice(-MAX_EVENTS)
  }
  setState(patch)
}

