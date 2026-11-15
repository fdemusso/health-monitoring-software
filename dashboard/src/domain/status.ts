import type { Emergency, NPCState } from '@/telemetry'
import { VITAL } from './vitalKeys'

export type Status = 'ok' | 'warn' | 'crit'
const RANK: Record<Status, number> = { ok: 0, warn: 1, crit: 2 }
export const maxStatus = (...s: Status[]): Status => s.reduce((a, b) => (RANK[b] > RANK[a] ? b : a), 'ok' as Status)

/** ESTIMATE: thresholds to be confirmed with Luca. */
export function vitalStatus(key: string, value: number | undefined, activity = ''): Status {
  if (value == null || !Number.isFinite(value)) return 'ok'
  switch (key) {
    case VITAL.spo2: return value < 90 ? 'crit' : value < 95 ? 'warn' : 'ok'
    case VITAL.coreTemp: return value >= 38.5 ? 'crit' : value >= 37.8 ? 'warn' : 'ok'
    case VITAL.hr:
      if (activity.startsWith('exercise')) return 'ok' // HR ~140 is normal during exercise
      // ESTIMATE: sleeping HR can sit in the 40s, so the low warning drops to 40 (crit 35) during sleep.
      if (activity === 'sleep') return value > 130 || value < 35 ? 'crit' : value > 100 || value < 40 ? 'warn' : 'ok'
      return value > 130 || value < 40 ? 'crit' : value > 100 || value < 50 ? 'warn' : 'ok'
    case VITAL.resp: return value >= 28 ? 'crit' : value >= 22 ? 'warn' : 'ok'
    case VITAL.cohb: return value >= 15 ? 'crit' : value >= 5 ? 'warn' : 'ok'
    default: return 'ok'
  }
}

/** ESTIMATE: 0 ok, 1 warn, >=2 crit (to confirm with Luca). */
export const healthStateStatus = (v: number | undefined): Status => (v == null ? 'ok' : v >= 2 ? 'crit' : v >= 1 ? 'warn' : 'ok')

const sevStatus = (s: number): Status => (s >= 0.75 ? 'crit' : s >= 0.4 ? 'warn' : 'ok')

export function crewStatus(npc: NPCState, emergencies: Emergency[]): Status {
  const parts: Status[] = [
    vitalStatus(VITAL.spo2, npc.vitals[VITAL.spo2]),
    vitalStatus(VITAL.coreTemp, npc.vitals[VITAL.coreTemp]),
    vitalStatus(VITAL.hr, npc.vitals[VITAL.hr], npc.activity),
    vitalStatus(VITAL.resp, npc.vitals[VITAL.resp]),
    vitalStatus(VITAL.cohb, npc.vitals[VITAL.cohb]),
    healthStateStatus(npc.vitals[VITAL.healthState]),
  ]
  if (npc.severity) for (const v of Object.values(npc.severity)) parts.push(sevStatus(v))
  for (const e of emergencies)
    if (e.state !== 'cleared' && e.subject === npc.id) parts.push(e.severity === 'critical' ? 'crit' : 'warn')
  if (npc.response_phase === 'incapacitated') parts.push('crit')
  return maxStatus(...parts)
}

/** Primary emergency + the others. Confirmed first, then critical, then oldest. */
export function primaryEmergency(emergencies: Emergency[]): { primary: Emergency | null; others: Emergency[] } {
  const live = emergencies.filter((e) => e.state !== 'cleared')
  live.sort(
    (a, b) =>
      Number(a.state !== 'confirmed') - Number(b.state !== 'confirmed') ||
      Number(a.severity !== 'critical') - Number(b.severity !== 'critical') ||
      a.t_open_s - b.t_open_s,
  )
  return { primary: live[0] ?? null, others: live.slice(1) }
}

export const isCriticalConfirmed = (e: Emergency | null) => !!e && e.state === 'confirmed' && e.severity === 'critical'

export function globalStatus(npcs: NPCState[], emergencies: Emergency[]): Status {
  const { primary } = primaryEmergency(emergencies)
  const fromEmergency: Status = !primary ? 'ok' : isCriticalConfirmed(primary) ? 'crit' : 'warn'
  return maxStatus(fromEmergency, ...npcs.map((n) => crewStatus(n, emergencies)))
}

export const statusLabel: Record<Status, string> = { ok: 'Stable', warn: 'Warning', crit: 'Critical' }
export const statusText: Record<Status, string> = { ok: 'text-status-live-foreground', warn: 'text-status-warning-foreground', crit: 'text-status-danger-foreground' }
/** Solid status colours, for dots, bars and chart marks (never behind text). */
export const statusColor: Record<Status, string> = { ok: 'var(--status-live)', warn: 'var(--status-warning)', crit: 'var(--status-danger)' }

export const RANKED = (s: Status) => RANK[s]
