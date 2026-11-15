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
  /** Carbon monoxide, ppm. */
  co_ppm: number;
  /** Smoke particulates, mg/m3. */
  smoke_mg_m3: number;
  /** Ventilation; the monitor switches it off in a fire. */
  fans_on: boolean;
}

/**
 * Vital signs the engine may provide. The set is open: the bioengineer decides which exist, so any
 * key is allowed. These are the ones the placeholder model currently emits.
 */
export type VitalName = 'hr' | 'hrv_rmssd' | 'spo2' | 'resp_rate' | 'skin_temp_c' | 'cohb_pct' | (string & {});

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
  sex?: 'M' | 'F' | null;
  age_y?: number | null;
  height_cm?: number | null;
  body_mass_kg?: number | null;
  /** TRUE vital signs (ground truth), keyed by {@link VitalName}. */
  /** Emergency role (incident_commander, systems, medical, sensing) or null outside an emergency. */
  role?: string | null;
  /** warn | gather | work | assist | evacuate | repair | incapacitated, or null outside an emergency. */
  response_phase?: string | null;
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
  /** Gas exchange now (passive + fan flow while open), m3/s. */
  diffusion_coeff: number;
  open: boolean;
  /** `H-<a>-<b>` unless the layout names it; faults and commands target it. */
  id: string;
  /** False for the ventilated crew-quarters openings. */
  closable: boolean;
}

/** Orbit and electrical bus (absent in profiles without an orbit). */
export interface StationState {
  /** 1 in sunlight, 0 in eclipse. */
  sun: number;
  beta_deg: number;
  /** 0..1 along the 92.8 min orbit. */
  orbit_phase: number;
  /** Battery state of charge, 0..1. */
  soc: number;
  p_gen_w: number;
  p_load_w: number;
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
  station: StationState | null;
  /** Telemetry channels of each actuator (CDRA bed temperatures, OGA stack voltage, fan speed ...), keyed by actuator id. */
  actuators: Record<string, Record<string, number>>;
  /** Ids of the faults active in this tick. */
  active_faults: string[];
  alarms: AlarmEvent[];
  /** Emergencies the monitor knows, from `suspected` until `cleared`. */
  emergencies: Emergency[];
  /** Steps waiting for a human: anyone may approve or reject. */
  pending_actions: PendingAction[];
  /** Monitor log lines produced since the previous tick the backend sent (frames can skip ticks; none is lost). */
  monitor_events: MonitorEvent[];
}

export type EmergencyKind = 'depressurization' | 'fire' | 'toxic' | 'equipment' | 'medical';
export type EmergencyState = 'suspected' | 'confirmed' | 'cleared';

export interface Emergency {
  id: string;
  kind: EmergencyKind;
  module_id: string;
  severity: string;
  state: EmergencyState;
  t_open_s: number;
  t_update_s: number;
  detectors: string[];
  /** Time to the minimum safe pressure, s (depressurization only). */
  tres_s: number | null;
  detail: string;
  /** Crew member in trouble (medical emergencies). */
  subject: string | null;
  /** What the sensors say is wrong, e.g. `co_poisoning`. */
  cause: string | null;
}

export interface Action {
  id: string;
  emergency_id: string;
  kind: 'actuator' | 'hatch' | 'announce' | 'ventilation' | 'extinguish';
  /** Already resolved: an actuator id, `a:b` for a hatch, a module id. */
  target: string;
  command: string;
  value: number | null;
  level: 'auto' | 'confirm';
  reversible: boolean;
  reason: string;
}

/** A step waiting for confirmation. At `deadline_s` (simulation time) it is run or dropped per `on_timeout`. */
export interface PendingAction {
  action: Action;
  t_proposed_s: number;
  deadline_s: number;
  on_timeout: 'execute' | 'discard';
}

export interface MonitorEvent {
  t_s: number;
  kind:
    | 'emergency_opened' | 'emergency_confirmed' | 'emergency_cleared'
    | 'action_executed' | 'action_proposed' | 'action_approved' | 'action_rejected'
    | 'action_expired_executed' | 'action_expired_discarded' | 'action_blocked'
    | 'crew_alerted' | 'crew_gathered' | 'crew_evacuating' | 'crew_assisting' | 'crew_command_passed'
    | 'crew_stood_down' | 'crew_repairing' | 'crew_repaired' | 'crew_sealed';
  message: string;
  emergency_id: string | null;
  action_id: string | null;
  /** Who approved or rejected; null = the system. */
  by: string | null;
}

/** A fault/event as the backend accepts it (same shape as an entry of a scenario's faults file). */
export interface FaultSpec {
  id: string;
  type: string;
  targets: string[];
  /** Ignored by inject_event: the event starts now. */
  start_s?: number;
  duration_s?: number | null;
  params?: Record<string, number | string | boolean>;
  anomaly_type?: string;
  priority?: number;
}
