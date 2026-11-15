import { crewIdentity } from '@/domain/crewConfig'
import { moduleName } from '@/domain/names'
import type { FaultSpec } from '@/telemetry'

/**
 * Situations the cheat menu can cause on the official station (scenarios/station/). Each one is a real FaultSpec of the engine, tuned so the
 * app reacts within minutes of SIMULATED time (`hint`, measured on the nominal station): a module for the station ones, a crew member for the medical ones.
 * start_s is ignored by inject_event (the event starts now).
 */
export interface Scenario {
  key: string
  label: string
  /** What the app will show, and after how many simulated minutes. */
  hint: string
  target: 'module' | 'crew'
  make: (target: string) => FaultSpec
}

/** Event ids are `dbg_<key>_<target>_<timestamp>`: `eventName` reads them back. */
const uid = (key: string, target: string) => `dbg_${key}_${target}_${Date.now().toString(36)}`

export const STATION_SCENARIOS: Scenario[] = [
  { key: 'fire', label: 'Fire', hint: 'Fire alarm in seconds, the crew gathers', target: 'module',
    make: (m) => ({ id: uid('fire', m), type: 'fire', targets: [m], duration_s: 1800, params: { heat_w: 1000, fuel_kj: 600, smoke_mg_s: 2.0 }, anomaly_type: 'fire', priority: 10 }) },
  { key: 'leak', label: 'Rapid air leak', hint: 'Pressure alarm in ~1 min, crew retreats to the lifeboat', target: 'module',
    make: (m) => ({ id: uid('leak', m), type: 'leak', targets: [m], duration_s: 120, params: { kpa_min: 4.0 }, anomaly_type: 'leak', priority: 10 }) },
  { key: 'slowleak', label: 'Air leak', hint: 'Pressure alarm in 2 to 9 min, sooner in small modules', target: 'module',
    make: (m) => ({ id: uid('slowleak', m), type: 'leak', targets: [m], duration_s: 600, params: { kpa_min: 1.0 }, anomaly_type: 'slow_leak', priority: 9 }) },
  { key: 'co', label: 'Carbon monoxide', hint: 'Alarm in seconds, crew breathing it is poisoned', target: 'module',
    make: (m) => ({ id: uid('co', m), type: 'co_source', targets: [m], duration_s: 120, params: { mol_s: 0.01 }, anomaly_type: 'co_release', priority: 8 }) },
]

export const CREW_SCENARIOS: Scenario[] = [
  { key: 'af', label: 'Irregular heartbeat', hint: 'Heart rate 150, irregular ECG, alarm in ~5 min', target: 'crew',
    make: (c) => ({ id: uid('af', c), type: 'medical', targets: [c], duration_s: 900, params: { hr_to: 150, spo2_to: 92.5, arrhythmia: 'af', resp_delta: 3, ramp_s: 60 }, anomaly_type: 'atrial_fibrillation_suspected', priority: 8 }) },
  { key: 'svt', label: 'Racing heart', hint: 'Heart rate 180, alarm in ~4 min', target: 'crew',
    make: (c) => ({ id: uid('svt', c), type: 'medical', targets: [c], duration_s: 1320, params: { hr_to: 180, hrv_factor: 0.45, ramp_s: 35 }, anomaly_type: 'svt_suspected', priority: 8 }) },
  { key: 'brady', label: 'Slow heart', hint: 'Heart rate 38, warning in ~5 min', target: 'crew',
    make: (c) => ({ id: uid('brady', c), type: 'medical', targets: [c], duration_s: 4200, params: { hr_to: 38, ramp_s: 60 }, anomaly_type: 'bradycardia', priority: 7 }) },
  { key: 'fever', label: 'Fever', hint: 'Body temperature passes 37.8 °C (warning) in ~8 min', target: 'crew',
    make: (c) => ({ id: uid('fever', c), type: 'medical', targets: [c], duration_s: 21600, params: { core_temp_delta: 2.0, skin_temp_delta: 1.0, hrv_factor: 0.8, ramp_s: 120 }, anomaly_type: 'fever', priority: 6 }) },
  { key: 'infection', label: 'Chest infection', hint: 'Low blood oxygen and fast breathing, alarm in ~8 min', target: 'crew',
    make: (c) => ({ id: uid('infection', c), type: 'medical', targets: [c], duration_s: 36000, params: { core_temp_delta: 1.5, resp_delta: 8, spo2_delta: -6, ramp_s: 120 }, anomaly_type: 'respiratory_infection', priority: 6 }) },
]

const ALL = [...STATION_SCENARIOS, ...CREW_SCENARIOS]

/** Readable name of an active event: "Fire · Unity". Events that did not come from the menu show their own id. */
export function eventName(faultId: string): string {
  const [pre, key, target] = faultId.split('_')
  const s = pre === 'dbg' ? ALL.find((x) => x.key === key) : undefined
  if (!s || !target) return faultId
  return `${s.label} · ${s.target === 'crew' ? crewIdentity(target).first : moduleName(target)}`
}
