import type { ModuleState } from '@/telemetry'

/**
 * Derived environment quantities. Mirror of `src/ares3/sdk/types.py::ModuleState` properties and
 * `src/ares3/core/constants.py` (psat_kpa, inspired_po2_mmhg, MMHG_PER_KPA): keep in sync.
 */
export const MMHG_PER_KPA = 7.50062

/** Saturation vapour pressure, kPa (Magnus above 0 degC, over-ice form below). */
export function psatKpa(tC: number): number {
  return tC >= 0
    ? 0.61094 * Math.exp((17.625 * tC) / (tC + 243.04))
    : 0.6112 * Math.exp((22.46 * tC) / (tC + 272.62))
}

export const ppco2Mmhg = (m: ModuleState) => m.gas.co2 * MMHG_PER_KPA
export const rhPercent = (m: ModuleState) => (100 * m.gas.h2o) / psatKpa(m.temperature_c)
export function pio2Mmhg(m: ModuleState): number {
  const p = m.pressure_kpa
  return (p * MMHG_PER_KPA - 47) * (m.gas.o2 / (p - m.gas.h2o))
}

export const fmt0 = (v: number | undefined | null) => (v == null || !Number.isFinite(v) ? '—' : String(Math.round(v)))
export const fmt1 = (v: number | undefined | null) => (v == null || !Number.isFinite(v) ? '—' : v.toFixed(1))

/** mm:ss, for countdowns (negative clamps to 0). */
export function fmtClock(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

/** hh:mm:ss of simulated time. */
export function fmtHms(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  const h = Math.floor(s / 3600)
  return `${String(h).padStart(2, '0')}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}
