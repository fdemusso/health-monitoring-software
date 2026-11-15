import type { ModuleState } from '@/telemetry'
import { METRIC_NAME } from './names'
import { pio2Mmhg, ppco2Mmhg, rhPercent } from './units'

/**
 * Nominal ranges shown under each environment value.
 * Mirror of scenarios/environments/orbital_station.yaml (NASA-STD-3001). Source tags: see
 * docs/reference/ambientmonitor/verifica-dati.md. Keep in sync by hand.
 */
export type EnvMetric = 'temp' | 'rh' | 'pio2' | 'ppco2' | 'pressure' | 'co'

export interface MetricSpec {
  key: EnvMetric
  label: string
  /** Technical name, for a tooltip. */
  tech: string
  unit: string
  min: number | null
  max: number | null
  /** Text under the value. */
  nominal: string
  decimals: number
  read: (m: ModuleState) => number
}

export const ENV_METRICS: Record<EnvMetric, MetricSpec> = {
  temp: { key: 'temp', label: METRIC_NAME.temp.label, tech: METRIC_NAME.temp.tech, unit: '°C', min: 18, max: 27, nominal: 'normal 18–27', decimals: 1, read: (m) => m.temperature_c }, // [S6]
  rh: { key: 'rh', label: METRIC_NAME.rh.label, tech: METRIC_NAME.rh.tech, unit: '%', min: 25, max: 75, nominal: 'normal 25–75', decimals: 0, read: rhPercent }, // [S6]
  pio2: { key: 'pio2', label: METRIC_NAME.pio2.label, tech: METRIC_NAME.pio2.tech, unit: 'mmHg', min: 127, max: null, nominal: 'at least 127', decimals: 0, read: pio2Mmhg }, // [S20]
  ppco2: { key: 'ppco2', label: METRIC_NAME.ppco2.label, tech: METRIC_NAME.ppco2.tech, unit: 'mmHg', min: null, max: 3, nominal: 'at most 3', decimals: 1, read: ppco2Mmhg }, // [S6]
  pressure: { key: 'pressure', label: METRIC_NAME.pressure.label, tech: METRIC_NAME.pressure.tech, unit: 'kPa', min: 34.5, max: 103, nominal: 'normal 34.5–103', decimals: 1, read: (m) => m.pressure_kpa }, // [S6]
  // ESTIMATE: no CO limit in the profile; 35 ppm is the usual 8 h occupational limit (see toxicology-sources.md).
  co: { key: 'co', label: METRIC_NAME.co.label, tech: METRIC_NAME.co.tech, unit: 'ppm', min: null, max: 35, nominal: 'at most 35', decimals: 0, read: (m) => m.co_ppm },
}

/** Matches the engine's alarm `metric` strings to our keys (best effort, case-insensitive). */
export const ALARM_METRIC: Record<string, EnvMetric> = {
  temperature_c: 'temp', temp: 'temp', temperature: 'temp',
  rh: 'rh', rh_percent: 'rh', humidity: 'rh',
  pio2: 'pio2', pio2_mmhg: 'pio2', po2: 'pio2',
  ppco2: 'ppco2', ppco2_mmhg: 'ppco2',
  pressure: 'pressure', pressure_kpa: 'pressure',
  co: 'co', co_ppm: 'co',
}

/** Out-of-range test against the nominal limits (fallback when no engine alarm exists). */
export function limitStatus(spec: MetricSpec, value: number): 'ok' | 'warn' | 'crit' {
  const lo = spec.min, hi = spec.max
  if ((lo != null && value < lo) || (hi != null && value > hi)) {
    const span = Math.abs((hi ?? lo ?? 1) * 0.15) || 1
    const beyond = lo != null && value < lo ? lo - value : value - (hi as number)
    return beyond > span ? 'crit' : 'warn'
  }
  return 'ok'
}
