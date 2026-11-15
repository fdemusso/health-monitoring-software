import type { FaultSpec } from '@/telemetry'

/** Real FaultSpecs from scenarios/events/*_faults.yaml and tests/. start_s is ignored by inject_event. */
export interface InjectPreset { label: string; make: () => FaultSpec }
/** Event ids are `<prefix>_<timestamp>`, created by `uid` below. */
const uid = (p: string) => `${p}_${Date.now().toString(36)}`

export const INJECT_PRESETS: InjectPreset[] = [
  { label: 'Incendio LAB', make: () => ({ id: uid('fire'), type: 'fire', targets: ['lab'], duration_s: 1800, params: { heat_w: 1000, fuel_kj: 500, smoke_mg_s: 2.0 }, anomaly_type: 'fire', priority: 10 }) },
  { label: 'Perdita lenta HAB', make: () => ({ id: uid('leak'), type: 'leak', targets: ['hab'], params: { rate_per_s: 1e-5, repairable: false }, anomaly_type: 'pressure_leak', priority: 9 }) },
  // ESTIMATE: 3e-4 /s is the "fast leak" rate used in tests/test_depressurization.py for the LAB
  { label: 'Perdita rapida LAB', make: () => ({ id: uid('leakfast'), type: 'leak', targets: ['lab'], params: { rate_per_s: 3e-4 }, anomaly_type: 'slow_leak', priority: 9 }) },
  { label: 'Scrubber HAB offline', make: () => ({ id: uid('scrub'), type: 'actuator_offline', targets: ['scrubber_hab'], duration_s: 36000, anomaly_type: 'scrubber_failure', priority: 5 }) },
  { label: 'Fonte CO₂ HAB', make: () => ({ id: uid('co2'), type: 'co2_source', targets: ['hab'], duration_s: 7200, params: { mol_s: 0.003 }, anomaly_type: 'co2_release', priority: 8 }) },
  { label: 'Fonte CO HAB', make: () => ({ id: uid('co'), type: 'co_source', targets: ['hab'], params: { mol_s: 3.0e-3 }, anomaly_type: 'co_release', priority: 8 }) },
  { label: 'Fibrillazione ENG', make: () => ({ id: uid('af'), type: 'medical', targets: ['eng'], duration_s: 900, params: { hr_to: 150, spo2_to: 92.5, arrhythmia: 'af', resp_delta: 3, ramp_s: 60 }, anomaly_type: 'atrial_fibrillation_suspected', priority: 8 }) },
  { label: 'Febbre CMD', make: () => ({ id: uid('fever'), type: 'medical', targets: ['cmd'], duration_s: 21600, params: { core_temp_delta: 1.5, skin_temp_delta: 1.0, hrv_factor: 0.8, ramp_s: 3600 }, anomaly_type: 'fever', priority: 6 }) },
]

const PREFIX_LABEL: Record<string, string> = Object.fromEntries(
  INJECT_PRESETS.map((p) => [p.make().id.split('_')[0], p.label]),
)

/** Readable name of an active event: injected ones use the preset label, others show their id. */
export const eventName = (faultId: string) => PREFIX_LABEL[faultId.split('_')[0]] ?? faultId
