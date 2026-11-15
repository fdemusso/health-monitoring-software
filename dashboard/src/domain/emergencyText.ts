import type { Emergency, ModuleState, MonitorEvent, NPCState, SimulationTick } from '@/telemetry'
import { VITAL } from './vitalKeys'
import { fmt0, fmt1, ppco2Mmhg, pio2Mmhg } from './units'

// PLACEHOLDER texts: awaiting review by the team.
const moduleName = (id: string) => id.toUpperCase()

const CAUSE: Record<string, string> = { co_poisoning: 'Intossicazione da CO', hypoxia: 'Ipossia' }

export function emergencyTitle(e: Emergency): string {
  const m = moduleName(e.module_id)
  switch (e.kind) {
    case 'depressurization': return `Depressurizzazione in ${m}`
    case 'fire': return `Incendio in ${m}`
    case 'toxic': return `Contaminazione tossica in ${m}`
    case 'equipment': return `Guasto apparecchiatura in ${m}`
    case 'medical': return e.cause ? (CAUSE[e.cause] ?? e.cause) : 'Emergenza medica'
    default: return `Anomalia in ${m}`
  }
}

export const emergencyKindLabel = (e: Emergency) => emergencyTitle(e)

export const RESPONSE_PHASE: Record<string, string> = {
  warn: 'Allertato', gather: 'In raduno', work: 'Al lavoro', assist: 'Assiste un compagno',
  evacuate: 'In evacuazione', repair: 'In riparazione', incapacitated: 'Incapacitato',
}
export const ROLE_LABEL: Record<string, string> = {
  incident_commander: 'Comandante emergenza', systems: 'Sistemi', medical: 'Medico', sensing: 'Rilevamento',
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
    out.push({ label: `Pressione ${m}`, value: fmt1(mod?.pressure_kpa), unit: 'kPa' })
    out.push({ label: 'TRes', value: e.tres_s == null ? '—' : fmt1(e.tres_s / 60), unit: 'min' })
    out.push({ label: `PIO₂ ${m}`, value: mod ? fmt0(pio2Mmhg(mod)) : '—', unit: 'mmHg' })
  } else if (e.kind === 'fire') {
    out.push({ label: `Temp. ${m}`, value: fmt1(mod?.temperature_c), unit: '°C' })
    out.push({ label: `CO ${m}`, value: fmt0(mod?.co_ppm), unit: 'ppm' })
    out.push({ label: `Fumo ${m}`, value: fmt1(mod?.smoke_mg_m3), unit: 'mg/m³' })
  } else if (e.kind === 'toxic') {
    const cohb = mod ? Math.max(0, ...mod.occupants.map((o) => tick.npcs[o]?.vitals[VITAL.cohb] ?? 0)) : undefined
    out.push({ label: `CO ${m}`, value: fmt0(mod?.co_ppm), unit: 'ppm' })
    out.push({ label: 'COHb max occupanti', value: fmt1(cohb), unit: '%' })
    out.push({ label: `ppCO₂ ${m}`, value: mod ? fmt1(ppco2Mmhg(mod)) : '—', unit: 'mmHg' })
  } else if (e.kind === 'medical') {
    const who = (e.subject ?? '').toUpperCase()
    out.push({ label: `SpO₂ di ${who}`, value: fmt0(subject?.vitals[VITAL.spo2]), unit: '%' })
    out.push({ label: `FC di ${who}`, value: fmt0(subject?.vitals[VITAL.hr]), unit: 'bpm' })
    if (e.cause === 'co_poisoning') out.push({ label: `CO ${m}`, value: fmt0(mod?.co_ppm), unit: 'ppm' })
    else out.push({ label: `ppCO₂ ${m}`, value: mod ? fmt1(ppco2Mmhg(mod)) : '—', unit: 'mmHg' })
  } else {
    out.push({ label: moduleName(e.module_id), value: e.detail || '—', unit: '' })
  }
  return out
}

const EVENT_LABEL: Record<MonitorEvent['kind'], string> = {
  emergency_opened: 'Emergenza aperta', emergency_confirmed: 'Emergenza confermata', emergency_cleared: 'Emergenza risolta',
  action_executed: 'Azione eseguita', action_proposed: 'Azione proposta', action_approved: 'Azione approvata',
  action_rejected: 'Azione rifiutata', action_expired_executed: 'Azione scaduta (eseguita)',
  action_expired_discarded: 'Azione scaduta (scartata)', action_blocked: 'Azione bloccata',
  crew_alerted: 'Equipaggio allertato', crew_gathered: 'Equipaggio radunato', crew_evacuating: 'Evacuazione',
  crew_assisting: 'Assistenza', crew_command_passed: 'Comando passato', crew_stood_down: 'Fine emergenza',
  crew_repairing: 'Riparazione', crew_repaired: 'Riparato', crew_sealed: 'Sigillato',
}
export const eventLabel = (k: string) => EVENT_LABEL[k as MonitorEvent['kind']] ?? k
export const eventFamily = (k: string): 'emergency' | 'action' | 'crew' =>
  k.startsWith('emergency') ? 'emergency' : k.startsWith('action') ? 'action' : 'crew'

const ACTIVITY: Record<string, string> = {
  sleep: 'Riposo notturno', nominal: 'Attività normale', work: 'Al lavoro', rest: 'A riposo', meal: 'Pasto',
  recovery: 'Recupero', exercise_aerobic: 'Esercizio aerobico', exercise_resistive: 'Esercizio di forza',
}
/** Italian label for `NPCState.activity`; unknown values are shown as they are. */
export const activityLabel = (a: string) => ACTIVITY[a] ?? a
