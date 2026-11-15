import { crewIdentity } from './crewConfig'
import { moduleName } from './names'
import { primaryEmergency } from './status'
import type { Emergency, ProcedureSpec, ProcedureState, SimulationTick } from '@/telemetry'

/**
 * The procedure the backend would start for `e`: same rule as `ProcedureRunner._choose` (kind, then cause, then severity; the one that
 * names the cause wins over the generic one). Used for an emergency that is still only suspected (no procedure runs yet) and for the library.
 */
export function chooseProcedure(catalog: ProcedureSpec[], e: Pick<Emergency, 'kind' | 'cause' | 'severity'>): ProcedureSpec | null {
  const fits = catalog.filter((p) => p.emergency === e.kind && (p.severity == null || p.severity === e.severity) && (p.cause == null || p.cause === e.cause))
  fits.sort((a, b) => Number(a.cause == null) - Number(b.cause == null))
  return fits[0] ?? null
}

/** The running (or just finished) procedure of an emergency, as the backend reports it. */
export const procedureOf = (tick: SimulationTick, e: Emergency): ProcedureState | undefined => tick.procedures.find((p) => p.emergency_id === e.id)

/** `{subject}` / `{module}` of a catalog text, in words: the person's name and the module's name (or generic words in the library). */
export function fillText(text: string, e?: Pick<Emergency, 'subject' | 'module_id'>): string {
  return text
    .replaceAll('{subject}', e?.subject ? crewIdentity(e.subject).first : 'the crew member')
    .replaceAll('{module}', e ? moduleName(e.module_id) : 'the module')
}

/** Open emergencies, the one to deal with first at the top (confirmed, then critical, then oldest). */
export function openEmergencies(tick: SimulationTick): Emergency[] {
  const { primary, others } = primaryEmergency(tick.emergencies)
  return primary ? [primary, ...others] : []
}

/** Medical procedures carry the fixed notice (docs/monitor-ui.md). */
export const isMedical = (emergency: string) => emergency === 'medical'
