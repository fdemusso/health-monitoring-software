import type { Emergency, ModuleState, MonitorEvent, NPCState, SimulationTick } from '@/telemetry'
import { VITAL } from './vitalKeys'
import { fmt0, fmt1, ppco2Mmhg, pio2Mmhg } from './units'
import { moduleName } from './names'
import { anomalyTitle, causeText, humanEvidence } from './anomalyText'

// PLACEHOLDER texts: awaiting review by the team.
import { crewIdentity } from './crewConfig'

const CAUSE: Record<string, string> = { co_poisoning: 'Carbon monoxide poisoning', hypoxia: 'Low blood oxygen', crew_baseline: 'Vital signs unusual for this person' }
const medicalCause = (c: string | null) => (c ? CAUSE[c] ?? causeText(c) ?? c : null)

export function emergencyTitle(e: Emergency): string {
  const m = moduleName(e.module_id)
  const cause = causeText(e.cause)
  switch (e.kind) {
    case 'depressurization': return `Air leaking from ${m}`
    case 'fire': return `Fire in ${m}`
    case 'toxic': return `Toxic air in ${m}`
    case 'equipment': return cause ?? `Equipment failure in ${m}`
    case 'sensor_fault': return cause ?? `A sensor in ${m} gives odd readings`
    case 'anomaly': return anomalyTitle(e.detail)
    case 'medical': { const c = medicalCause(e.cause); return e.subject ? `${crewIdentity(e.subject).first}: ${c ? c.toLowerCase() : 'medical emergency'}` : c ?? 'Medical emergency' }
    default: return `Anomaly in ${m}`
  }
}

/** What the monitor saw, in plain words, for kinds that have no headline numbers (equipment, sensors, anomalies). */
export const seenLines = (e: Emergency, max = 3): string[] => e.evidence.map(humanEvidence).filter((l) => l !== emergencyTitle(e)).slice(0, max)

const RESPONSE_PHASE: Record<string, string> = {
  warn: 'Alerted', gather: 'Gathering', work: 'Working', assist: 'Assisting a crewmate',
  evacuate: 'Evacuating', repair: 'Repairing', incapacitated: 'Incapacitated',
}
export const ROLE_LABEL: Record<string, string> = {
  incident_commander: 'Incident commander', systems: 'Repairs', medical: 'Medic', sensing: 'Sensor watch',
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
    out.push({ label: `Air pressure, ${m}`, value: fmt1(mod?.pressure_kpa), unit: 'kPa' })
    out.push({ label: 'Time before unsafe air', value: e.tres_s == null ? '—' : fmt1(e.tres_s / 60), unit: 'min' })
    out.push({ label: `Oxygen, ${m}`, value: mod ? fmt0(pio2Mmhg(mod)) : '—', unit: 'mmHg' })
  } else if (e.kind === 'fire') {
    out.push({ label: `Temperature, ${m}`, value: fmt1(mod?.temperature_c), unit: '°C' })
    out.push({ label: `Carbon monoxide, ${m}`, value: fmt0(mod?.co_ppm), unit: 'ppm' })
    out.push({ label: `Smoke, ${m}`, value: fmt1(mod?.smoke_mg_m3), unit: 'mg/m³' })
  } else if (e.kind === 'toxic') {
    const cohb = mod ? Math.max(0, ...mod.occupants.map((o) => tick.npcs[o]?.vitals[VITAL.cohb] ?? 0)) : undefined
    out.push({ label: `Carbon monoxide, ${m}`, value: fmt0(mod?.co_ppm), unit: 'ppm' })
    out.push({ label: 'CO in blood (highest)', value: fmt1(cohb), unit: '%' })
    out.push({ label: `Carbon dioxide, ${m}`, value: mod ? fmt1(ppco2Mmhg(mod)) : '—', unit: 'mmHg' })
  } else if (e.kind === 'medical') {
    const who = e.subject ? crewIdentity(e.subject).first : ''
    out.push({ label: `${who}: blood oxygen`, value: fmt0(subject?.vitals[VITAL.spo2]), unit: '%' })
    out.push({ label: `${who}: heart rate`, value: fmt0(subject?.vitals[VITAL.hr]), unit: 'bpm' })
    if (e.cause === 'co_poisoning') out.push({ label: `Carbon monoxide, ${m}`, value: fmt0(mod?.co_ppm), unit: 'ppm' })
    else out.push({ label: `Carbon dioxide, ${m}`, value: mod ? fmt1(ppco2Mmhg(mod)) : '—', unit: 'mmHg' })
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
  crew_repairing: 'Repairing', crew_repaired: 'Repaired', crew_sealed: 'Lifeboat sealed',
  mode_changed: 'Alert level changed', procedure_started: 'Procedure started', step_done: 'Step done',
  step_failed: 'Step failed', procedure_done: 'Procedure done', procedure_escalated: 'Procedure escalated',
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
