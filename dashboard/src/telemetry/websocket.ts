/**
 * Adapters for the Python backend (`ares3 serve <scenario>`): a {@link VitalsSource} that receives ticks over a WebSocket
 * and a client for the commands the backend accepts. Protocol: `src/ares3/serve/session.py` (module docstring).
 */
import type { VitalsSource } from './contracts';
import type { EmergencyKind, FaultSpec, HistorySample, SimulationTick } from './types';

/** What the UI can ask of the running simulation (python: `sdk/control.py::ControlAPI`, plus pacing). */
export type ControlCommand =
  | { cmd: 'inject_event'; args: { fault: FaultSpec } }
  | { cmd: 'stop_event'; args: { fault_id: string } }
  | { cmd: 'approve_action'; args: { action_id: string; by?: string } }
  | { cmd: 'reject_action'; args: { action_id: string; by?: string } }
  | { cmd: 'ack_step'; args: { procedure_id: string; step_id: string; by?: string; answer?: 'yes' | 'no' } }
  | { cmd: 'declare_emergency'; args: { kind: EmergencyKind; module_id: string; by?: string } }
  | { cmd: 'pause'; args?: Record<string, never> }
  | { cmd: 'resume'; args?: Record<string, never> }
  | { cmd: 'set_speed'; args: { speed: number } }
  | { cmd: 'reset'; args?: Record<string, never> };

export interface BackendHello {
  scenario: string;
  dt_s: number;
  paused: boolean;
  speed: number;
  /** `warming`: the server is running the simulation ahead (`--warmup-h`); no ticks and no commands until `ready`. */
  state: 'warming' | 'live';
}

/** Progress of the server's warm-up, sent about four times a second while `state` is `warming`. */
export interface WarmupProgress {
  /** 0..1 */
  progress: number;
  sim_s: number;
  total_s: number;
}

/** Playback state sent with every tick. */
export interface BackendStatus {
  paused: boolean;
  /** Simulated seconds per real second. */
  speed: number;
}

export interface CommandResult {
  ok: boolean;
  error?: string;
  /** E.g. the scheduled fault for `inject_event`, the emergency id for `declare_emergency`. */
  data?: unknown;
}

type ServerMessage =
  | ({ type: 'hello' } & BackendHello)
  | ({ type: 'tick'; tick: SimulationTick } & BackendStatus)
  | { type: 'history'; samples: HistorySample[] }
  | ({ type: 'warming' } & WarmupProgress)
  | { type: 'ready' }
  | ({ type: 'result'; id: number } & CommandResult);

export interface WebSocketBackendOptions {
  /** Default `ws://127.0.0.1:8765`, what `ares3 serve` listens on. */
  url?: string;
  /** Milliseconds before reconnecting after the connection drops. Default 2000; 0 disables. */
  reconnectMs?: number;
  onHello?: (hello: BackendHello) => void;
  /** The last hours of the simulation, sent once right after `hello`: fills the charts at once. */
  onHistory?: (samples: HistorySample[]) => void;
  onStatus?: (status: BackendStatus) => void;
  /** Warm-up progress while the server runs ahead; `null` once it is over (or if the server never warmed up). */
  onWarming?: (progress: WarmupProgress | null) => void;
  /** `true` while the socket is open. */
  onConnection?: (connected: boolean) => void;
}

/**
 * One connection serving both roles: `subscribe` (ticks in) and `send` (commands out). A single instance can be
 * used as the `VitalsSource` and as the control client.
 */
export class WebSocketBackend implements VitalsSource {
  private readonly url: string;
  private readonly reconnectMs: number;
  private readonly options: WebSocketBackendOptions;
  private socket: WebSocket | null = null;
  private listeners = new Set<(tick: SimulationTick) => void>();
  private waiting = new Map<number, (r: CommandResult) => void>();
  private nextId = 1;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private closed = true;

  constructor(options: WebSocketBackendOptions = {}) {
    this.options = options;
    this.url = options.url ?? 'ws://127.0.0.1:8765';
    this.reconnectMs = options.reconnectMs ?? 2000;
  }

  subscribe(onTick: (tick: SimulationTick) => void): () => void {
    this.listeners.add(onTick);
    if (this.closed) this.open();
    return () => {
      this.listeners.delete(onTick);
      if (this.listeners.size === 0) this.close();
    };
  }

  /** Sends a command; resolves with the backend's answer (never rejects on a refused command: check `ok`). */
  send(command: ControlCommand): Promise<CommandResult> {
    const socket = this.socket;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return Promise.resolve({ ok: false, error: 'not connected to the backend' });
    }
    const id = this.nextId++;
    return new Promise((resolve) => {
      this.waiting.set(id, resolve);
      socket.send(JSON.stringify({ type: 'command', id, cmd: command.cmd, args: command.args ?? {} }));
    });
  }

  private open(): void {
    this.closed = false;
    const socket = new WebSocket(this.url);
    this.socket = socket;
    socket.onopen = () => this.options.onConnection?.(true);
    socket.onmessage = (ev: MessageEvent<string>) => this.onMessage(JSON.parse(ev.data) as ServerMessage);
    socket.onclose = () => {
      this.options.onConnection?.(false);
      for (const resolve of this.waiting.values()) resolve({ ok: false, error: 'connection closed' });
      this.waiting.clear();
      this.socket = null;
      if (!this.closed && this.reconnectMs > 0) this.timer = setTimeout(() => this.open(), this.reconnectMs);
    };
  }

  private close(): void {
    this.closed = true;
    if (this.timer) clearTimeout(this.timer);
    this.socket?.close();
  }

  private onMessage(msg: ServerMessage): void {
    if (msg.type === 'tick') {
      this.options.onStatus?.({ paused: msg.paused, speed: msg.speed });
      for (const listener of this.listeners) listener(msg.tick);
    } else if (msg.type === 'hello') {
      this.options.onHello?.(msg);
      if (msg.state === 'live') this.options.onWarming?.(null);
    } else if (msg.type === 'warming') {
      this.options.onWarming?.(msg);
    } else if (msg.type === 'ready') {
      this.options.onWarming?.(null);
    } else if (msg.type === 'history') {
      this.options.onHistory?.(msg.samples);
    } else {
      const resolve = this.waiting.get(msg.id);
      this.waiting.delete(msg.id);
      resolve?.({ ok: msg.ok, error: msg.error, data: msg.data });
    }
  }
}
