import type { OrganVitals } from '../types/anatomy';
import type { ModuleState, NPCState, SimulationTick } from './types';

/**
 * Where ticks come from. Transport-agnostic on purpose: a WebSocket to the Python backend, a replay
 * of an exported dataset, or a fake generator for tests all implement the same interface.
 */
export interface VitalsSource {
  /** Start receiving ticks. Returns the function that stops the subscription. */
  subscribe(onTick: (tick: SimulationTick) => void): () => void;
}

/**
 * Turns the engine's data into what `<BodyHologram />` renders.
 *
 * `BodyHologram` takes `OrganVitals`: heart in bpm, lungs in breaths/min, the other organs as a
 * severity in 0..1. How engine signals map onto organs (for example SpO2 or ppCO2 onto brain or
 * lungs) is a decision for the bioengineer, so it lives in an adapter, never in the component.
 *
 * Intentionally NOT implemented yet.
 */
export interface VitalsAdapter {
  /**
   * @param npc The astronaut to display.
   * @param module The module the astronaut is in (environment context for thresholds).
   * @param tick The whole tick, for anything else the mapping needs (time of day, alarms, faults).
   */
  toOrganVitals(npc: NPCState, module: ModuleState, tick: SimulationTick): OrganVitals;
}
