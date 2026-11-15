import { pio2Mmhg, ppco2Mmhg, rhPercent } from '@/domain/units'
import type { MonitorEvent, SimulationTick } from './types'

/** History sampling period, simulated seconds. */
export const SAMPLE_S = 60
export const MAX_SAMPLES = 360 // 6 h
export const MAX_EVENTS = 200

export interface CrewSample { t: number; hr?: number; spo2?: number; resp?: number; core?: number; cohb?: number }
export interface ModuleSample { t: number; temp: number; rh: number; pio2: number; ppco2: number; pressure: number; co: number }

export interface TelemetryState {
  tick: SimulationTick | null
  /** Wall-clock ms of the last received tick. */
  lastTickAt: number
  connected: boolean
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
  tick: null, lastTickAt: 0, connected: false, paused: false, speed: 0, scenario: null, url: '',
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
    const ch: Record<string, CrewSample[]> = { ...crewHistory }
    for (const [id, n] of Object.entries(tick.npcs)) {
      const s: CrewSample = {
        t: tick.t_sim_s, hr: n.vitals.hr, spo2: n.vitals.spo2, resp: n.vitals.resp_rate,
        core: n.vitals.core_temp_c, cohb: n.vitals.cohb_pct,
      }
      ch[id] = [...(ch[id] ?? []), s].slice(-MAX_SAMPLES)
    }
    const mh: Record<string, ModuleSample[]> = { ...moduleHistory }
    for (const [id, m] of Object.entries(tick.modules)) {
      const s: ModuleSample = {
        t: tick.t_sim_s, temp: m.temperature_c, rh: rhPercent(m), pio2: pio2Mmhg(m),
        ppco2: ppco2Mmhg(m), pressure: m.pressure_kpa, co: m.co_ppm,
      }
      mh[id] = [...(mh[id] ?? []), s].slice(-MAX_SAMPLES)
    }
    patch.crewHistory = ch; patch.moduleHistory = mh
  }

  if (tick.monitor_events?.length) {
    const seen = new Set(state.eventLog.map(eventKey))
    const fresh = tick.monitor_events.filter((e) => !seen.has(eventKey(e)))
    if (fresh.length) patch.eventLog = [...(patch.eventLog ?? state.eventLog), ...fresh].slice(-MAX_EVENTS)
  }
  setState(patch)
}

