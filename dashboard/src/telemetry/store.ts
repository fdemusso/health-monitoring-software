import { isFrozen, whenThawed } from '@/lib/dragFreeze'
import { pio2Mmhg, ppco2Mmhg, rhPercent } from '@/domain/units'
import type { WarmupProgress } from './websocket'
import type { HistorySample, ModuleState, MonitorEvent, SimulationTick, VitalsSample } from './types'

/** Modules: one sample per simulated minute, 6 h (mirror of `HISTORY_STEP_S` / `HISTORY_LEN` in serve/session.py). */
const MODULE_STEP_S = 60
const MODULE_MAX = 360
/** Crew vitals: one sample per 10 simulated seconds, 6 h (`VITALS_STEP_S` / `VITALS_LEN`): a 15-minute window still has 90 points. */
const CREW_STEP_S = 10
const CREW_MAX = 2160
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
  /** Seconds to add to `t_sim_s` to get the time of day on board (the charts label their time axis with it). */
  clockOffsetS: number
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
  tick: null, lastTickAt: 0, connected: false, clockOffsetS: 0, warming: null, paused: false, speed: 0, scenario: null, url: '',
  crewHistory: {}, moduleHistory: {}, eventLog: [], commandError: null,
}
const listeners = new Set<() => void>()
let lastCrewT = -Infinity
let lastModuleT = -Infinity

export const getState = () => state
export function subscribe(l: () => void) {
  listeners.add(l)
  return () => { listeners.delete(l) }
}
let missed = false // a change arrived while the UI was frozen (a panel is being dragged)
const notify = () => { for (const l of listeners) l() }
whenThawed(() => { if (missed) { missed = false; notify() } })

export function setState(patch: Partial<TelemetryState>) {
  state = { ...state, ...patch }
  if (isFrozen()) missed = true
  else notify()
}

const eventKey = (e: MonitorEvent) => `${e.t_s}|${e.kind}|${e.emergency_id}|${e.action_id}`

type Wearables = Record<string, Record<string, number>>

const crewSample = (t: number, r: Record<string, number | undefined>): CrewSample =>
  ({ t, hr: r.hr, spo2: r.spo2, resp: r.resp_rate, core: r.core_temp_c, cohb: r.cohb_pct })

/** What the wearables read (measured); a server that does not send them falls back to the ground truth of the tick. */
const crewReadings = (tick: Pick<SimulationTick, 'npcs' | 'wearables'>): Wearables =>
  tick.wearables ?? Object.fromEntries(Object.entries(tick.npcs).map(([id, n]) => [id, { ...n.vitals }]))

const moduleSample = (t: number, m: ModuleState): ModuleSample =>
  ({ t, temp: m.temperature_c, rh: rhPercent(m), pio2: pio2Mmhg(m), ppco2: ppco2Mmhg(m), pressure: m.pressure_kpa, co: m.co_ppm })

const pushCapped = <T,>(list: T[] | undefined, item: T, max: number): T[] => {
  const out = list ? [...list, item] : [item]
  return out.length > max ? out.slice(out.length - max) : out
}

/** The history the backend sends once after `hello`: replaces whatever was gathered so far (a reconnection starts from it too). */
export function ingestHistory(samples: HistorySample[], vitals: VitalsSample[]) {
  const ch: Record<string, CrewSample[]> = {}
  for (const v of vitals)
    for (const [id, r] of Object.entries(v.w)) (ch[id] ??= []).push(crewSample(v.t_sim_s, r))
  const mh: Record<string, ModuleSample[]> = {}
  for (const snap of samples) {
    for (const [id, m] of Object.entries(snap.modules)) (mh[id] ??= []).push(moduleSample(snap.t_sim_s, m))
    // an older server sends no `vitals`: the per-minute ground truth is better than an empty chart
    if (!vitals.length)
      for (const [id, r] of Object.entries(crewReadings(snap))) (ch[id] ??= []).push(crewSample(snap.t_sim_s, r))
  }
  if (vitals.length) lastCrewT = vitals[vitals.length - 1].t_sim_s
  else if (samples.length) lastCrewT = samples[samples.length - 1].t_sim_s
  if (samples.length) lastModuleT = samples[samples.length - 1].t_sim_s
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
    crewHistory = {}; moduleHistory = {}; lastCrewT = -Infinity; lastModuleT = -Infinity
    patch.crewHistory = crewHistory; patch.moduleHistory = moduleHistory; patch.eventLog = []
  }
  patch.clockOffsetS = (((tick.time_of_day_h * 3600 - tick.t_sim_s) % 86400) + 86400) % 86400

  if (tick.t_sim_s - lastCrewT >= CREW_STEP_S) {
    lastCrewT = tick.t_sim_s
    const ch = { ...crewHistory }
    for (const [id, r] of Object.entries(crewReadings(tick))) ch[id] = pushCapped(ch[id], crewSample(tick.t_sim_s, r), CREW_MAX)
    patch.crewHistory = crewHistory = ch
  }
  if (tick.t_sim_s - lastModuleT >= MODULE_STEP_S) {
    lastModuleT = tick.t_sim_s
    const mh = { ...moduleHistory }
    for (const [id, m] of Object.entries(tick.modules)) mh[id] = pushCapped(mh[id], moduleSample(tick.t_sim_s, m), MODULE_MAX)
    patch.moduleHistory = mh
  }

  if (tick.monitor_events?.length) {
    const seen = new Set(state.eventLog.map(eventKey))
    const fresh = tick.monitor_events.filter((e) => !seen.has(eventKey(e)))
    if (fresh.length) patch.eventLog = [...(patch.eventLog ?? state.eventLog), ...fresh].slice(-MAX_EVENTS)
  }
  setState(patch)
}

