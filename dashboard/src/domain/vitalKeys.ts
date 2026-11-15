/** Names of the keys in `NPCState.vitals` (open set, see telemetry/types.ts). */
export const VITAL = {
  hr: 'hr',
  hrv: 'hrv_rmssd',
  spo2: 'spo2',
  resp: 'resp_rate',
  skinTemp: 'skin_temp_c',
  coreTemp: 'core_temp_c',
  healthState: 'health_state',
  gasScale: 'gas_scale',
  cohb: 'cohb_pct',
} as const
