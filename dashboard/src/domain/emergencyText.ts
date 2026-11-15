import type { Emergency, ModuleState, MonitorEvent, NPCState, SimulationTick } from '@/telemetry'
import { VITAL } from './vitalKeys'
import { fmt0, fmt1, ppco2Mmhg, pio2Mmhg } from './units'

// PLACEHOLDER texts: awaiting review by the team.
const moduleName = (id: string) => id.toUpperCase()

const CAUSE: Record<string, string> = { co_poisoning: 'CO poisoning', hypoxia: 'Hypoxia' }

export function emergencyTitle(e: Emergency): string {
  const m = moduleName(e.module_id)
  switch (e.kind) {
    case 'depressurization': return `Depressurization in ${m}`
    case 'fire': return `Fire in ${m}`
    case 'toxic': return `Toxic contamination in ${m}`
    case 'equipment': return `Equipment failure in ${m}`
    case 'medical': return e.cause ? (CAUSE[e.cause] ?? e.cause) : 'Medical emergency'
    default: return `Anomaly in ${m}`
  }
}

export const emergencyKindLabel = (e: Emergency) => emergencyTitle(e)

export const RESPONSE_PHASE: Record<string, string> = {
  warn: 'Alerted', gather: 'Gathering', work: 'Working', assist: 'Assisting a crewmate',
  evacuate: 'Evacuating', repair: 'Repairing', incapacitated: 'Incapacitated',
}
export const ROLE_LABEL: Record<string, string> = {
  incident_commander: 'Incident commander', systems: 'Systems', medical: 'Medic', sensing: 'Sensing',
}
export const phaseLabel = (p: string | null | undefined) => (p ? (RESPONSE_PHASE[p] ?? p) : null)

export interface KeyNumber { label: string; value: string; unit: string }

/** The three headline numbers of the banner, per emergency kind. */
export function keyNumbers(e: Emergency, tick: SimulationTick): KeyNumber[] {
  const mod: ModuleState | undefined = tick.modules[e.module_id]
  const subject: NPCState | undefined = e.subject ? tick.npcs[e.subject] : undefined
  const m = moduleName(e.module_id)
  const out: KeyNumber[] = []
  if (e.kind === 'depressurization') {
    out.push({ label: `Pressure ${m}`, value: fmt1(mod?.pressure_kpa), unit: 'kPa' })
    out.push({ label: 'TRes', value: e.tres_s == null ? '—' : fmt1(e.tres_s / 60), unit: 'min' })
    out.push({ label: `PIO₂ ${m}`, value: mod ? fmt0(pio2Mmhg(mod)) : '—', unit: 'mmHg' })
  } else if (e.kind === 'fire') {
    out.push({ label: `Temp. ${m}`, value: fmt1(mod?.temperature_c), unit: '°C' })
    out.push({ label: `CO ${m}`, value: fmt0(mod?.co_ppm), unit: 'ppm' })
    out.push({ label: `Smoke ${m}`, value: fmt1(mod?.smoke_mg_m3), unit: 'mg/m³' })
  } else if (e.kind === 'toxic') {
    const cohb = mod ? Math.max(0, ...mod.occupants.map((o) => tick.npcs[o]?.vitals[VITAL.cohb] ?? 0)) : undefined
    out.push({ label: `CO ${m}`, value: fmt0(mod?.co_ppm), unit: 'ppm' })
    out.push({ label: 'Max occupant COHb', value: fmt1(cohb), unit: '%' })
    out.push({ label: `ppCO₂ ${m}`, value: mod ? fmt1(ppco2Mmhg(mod)) : '—', unit: 'mmHg' })
  } else if (e.kind === 'medical') {
    const who = (e.subject ?? '').toUpperCase()
    out.push({ label: `${who} SpO₂`, value: fmt0(subject?.vitals[VITAL.spo2]), unit: '%' })
    out.push({ label: `${who} HR`, value: fmt0(subject?.vitals[VITAL.hr]), unit: 'bpm' })
    if (e.cause === 'co_poisoning') out.push({ label: `CO ${m}`, value: fmt0(mod?.co_ppm), unit: 'ppm' })
    else out.push({ label: `ppCO₂ ${m}`, value: mod ? fmt1(ppco2Mmhg(mod)) : '—', unit: 'mmHg' })
  } else {
    out.push({ label: moduleName(e.module_id), value: e.detail || '—', unit: '' })
  }
  return out
}

const EVENT_LABEL: Record<MonitorEvent['kind'], string> = {
  emergency_opened: 'Emergency opened', emergency_confirmed: 'Emergency confirmed', emergency_cleared: 'Emergency cleared',
  action_executed: 'Action executed', action_proposed: 'Action proposed', action_approved: 'Action approved',
  action_rejected: 'Action rejected', action_expired_executed: 'Action expired (executed)',
  action_expired_discarded: 'Action expired (discarded)', action_blocked: 'Action blocked',
  crew_alerted: 'Crew alerted', crew_gathered: 'Crew gathered', crew_evacuating: 'Evacuation',
  crew_assisting: 'Assisting', crew_command_passed: 'Command handed over', crew_stood_down: 'Stand down',
  crew_repairing: 'Repairing', crew_repaired: 'Repaired', crew_sealed: 'Sealed',
}
export const eventLabel = (k: string) => EVENT_LABEL[k as MonitorEvent['kind']] ?? k
export const eventFamily = (k: string): 'emergency' | 'action' | 'crew' =>
  k.startsWith('emergency') ? 'emergency' : k.startsWith('action') ? 'action' : 'crew'

const ACTIVITY: Record<string, string> = {
  sleep: 'Night sleep', nominal: 'Normal activity', work: 'Working', rest: 'Resting', meal: 'Meal',
  recovery: 'Recovery', exercise_aerobic: 'Aerobic exercise', exercise_resistive: 'Resistance exercise',
}
/** English label for `NPCState.activity`; unknown values are shown as they are. */
export const activityLabel = (a: string) => ACTIVITY[a] ?? a
