import { useCallback, useMemo, useSyncExternalStore } from 'react'
import { sortCrewIds } from '@/domain/crewConfig'
import { backend } from './createBackend'
import { getState, setState, subscribe, type TelemetryState } from './store'
import type { CommandResult } from './websocket'
import type { Emergency, FaultSpec, EmergencyKind, ModuleState, NPCState, PendingAction } from './types'

export function useStore<T>(selector: (s: TelemetryState) => T): T {
  return useSyncExternalStore(subscribe, () => selector(getState()))
}

const EMPTY_E: Emergency[] = []
const EMPTY_P: PendingAction[] = []

export const useTick = () => useStore((s) => s.tick)
export const useEmergencies = () => useStore((s) => s.tick?.emergencies ?? EMPTY_E)
export const usePendingActions = () => useStore((s) => s.tick?.pending_actions ?? EMPTY_P)
export const useCatalog = () => useStore((s) => s.catalog)
export const useEventLog = () => useStore((s) => s.eventLog)
export const useCrewHistory = (id: string) => useStore((s) => s.crewHistory[id])
export const useAllCrewHistory = () => useStore((s) => s.crewHistory)
export const useModuleHistory = (id: string) => useStore((s) => s.moduleHistory[id])
/** Non-null while the server warms up (and during the short fade-out after it). */
export const useWarmup = () => useStore((s) => s.warming)
/** True until the first thing arrives from the backend (a tick or a warm-up report): the port may not even be open yet. */
export const useWaiting = () => useStore((s) => s.tick === null && s.warming === null)
export const useBackendStatus = () => ({
  connected: useStore((s) => s.connected),
  paused: useStore((s) => s.paused),
  speed: useStore((s) => s.speed),
  scenario: useStore((s) => s.scenario),
  url: useStore((s) => s.url),
  lastTickAt: useStore((s) => s.lastTickAt),
  commandError: useStore((s) => s.commandError),
})

export function useCrewList(): NPCState[] {
  const npcs = useStore((s) => s.tick?.npcs)
  return useMemo(() => (npcs ? sortCrewIds(Object.keys(npcs)).map((id) => npcs[id]) : []), [npcs])
}
export function useModuleList(): ModuleState[] {
  const mods = useStore((s) => s.tick?.modules)
  return useMemo(() => (mods ? Object.values(mods) : []), [mods])
}

/** Typed wrappers over backend.send. `by` is only a log label. */
export function useCommands() {
  const run = useCallback(async (p: Promise<CommandResult>) => {
    const r = await p
    setState({ commandError: r.ok ? null : (r.error ?? 'comando rifiutato') })
    return r
  }, [])
  return useMemo(() => ({
    approve: (action_id: string) => run(backend.send({ cmd: 'approve_action', args: { action_id, by: 'ui' } })),
    /** Closes the active step of a procedure (`answer` only for a question). */
    ackStep: (procedure_id: string, step_id: string, answer?: 'yes' | 'no') => run(backend.send({ cmd: 'ack_step', args: { procedure_id, step_id, by: 'ui', ...(answer ? { answer } : {}) } })),
    reject: (action_id: string) => run(backend.send({ cmd: 'reject_action', args: { action_id, by: 'ui' } })),
    inject: (fault: FaultSpec) => run(backend.send({ cmd: 'inject_event', args: { fault } })),
    stopEvent: (fault_id: string) => run(backend.send({ cmd: 'stop_event', args: { fault_id } })),
    declare: (kind: EmergencyKind, module_id: string) => run(backend.send({ cmd: 'declare_emergency', args: { kind, module_id, by: 'ui' } })),
    pause: () => run(backend.send({ cmd: 'pause' })),
    resume: () => run(backend.send({ cmd: 'resume' })),
    setSpeed: (speed: number) => run(backend.send({ cmd: 'set_speed', args: { speed } })),
    reset: () => run(backend.send({ cmd: 'reset' })),
  }), [run])
}
