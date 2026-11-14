/**
 * TypeScript mirror of the simulation engine's data contract (`src/ares3/sdk/types.py`), as it
 * appears once a `SimulationTick` is serialized to JSON (pydantic `model_dump_json`).
 *
 * Units follow the engine: partial pressures in kPa, temperatures in degC, `heat_w` in W, volumes in m3.
 * Keep this file in sync with the Python side; the Python model is the source of truth.
 */

/** Partial pressures of each species in a module, kPa. */
export interface GasComposition {
  o2: number;
  co2: number;
  n2: number;
  h2o: number;
}

export interface ModuleState {
  id: string;
  volume_m3: number;
  temperature_c: number;
  pressure_kpa: number;
  gas: GasComposition;
  /** Net heat input of the module during the tick, W. */
  heat_load_w: number;
  /** Ids of the astronauts currently in the module. */
  occupants: string[];
}

/**
 * Vital signs the engine may provide. The set is open: the bioengineer decides which exist, so any
 * key is allowed. These are the ones the placeholder model currently emits.
 */
export type VitalName = 'hr' | 'hrv_rmssd' | 'spo2' | 'resp_rate' | 'skin_temp_c' | (string & {});

export interface NPCState {
  id: string;
  /** Free label: commander | engineer | medic | botanist | ... */
  profile: string;
  module_id: string;
  activity: string;
  met: number;
  vo2_l_min: number;
  vco2_l_min: number;
  heat_w: number;
  /** TRUE vital signs (ground truth), keyed by {@link VitalName}. */
  vitals: Record<VitalName, number>;
  /** Opaque persistent state of the physiology model. */
  latent: Record<string, number>;
  /**
   * Per-vital severity in 0..1 (0 normal, 0.5 borderline, 1 critical), computed by the engine from
   * thresholds that depend on activity and environment.
   *
   * PLANNED: the engine does not emit this yet. Until it does, an adapter has to derive severity
   * itself (see {@link VitalsAdapter}).
   */
  severity?: Record<VitalName, number>;
}

export interface AlarmEvent {
  code: string;
  module_id: string;
  metric: string;
  value: number;
  limit_min: number | null;
  limit_max: number | null;
  severity: 'warning' | 'alarm';
  source: string;
}

export interface HatchState {
  a: string;
  b: string;
  diffusion_coeff: number;
  open: boolean;
}

/** One simulation step, as pushed by the backend. */
export interface SimulationTick {
  tick: number;
  t_sim_s: number;
  dt_s: number;
  day: number;
  /** Local hours, 0..24. */
  time_of_day_h: number;
  modules: Record<string, ModuleState>;
  /** Keyed by astronaut id. */
  npcs: Record<string, NPCState>;
  hatches: HatchState[];
  /** Ids of the faults active in this tick. */
  active_faults: string[];
  alarms: AlarmEvent[];
}
