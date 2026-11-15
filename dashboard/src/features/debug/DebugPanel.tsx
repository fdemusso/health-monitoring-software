import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Sheet } from '@/components/ui/sheet'
import { StatusBadge } from '@/components/ui/status-badge'
import { ToggleGroup, ToggleGroupMulti } from '@/components/ui/toggle-group'
import type { EmergencyKind } from '@/telemetry'
import { useBackendStatus, useCommands, useModuleList, useTick } from '@/telemetry/useTelemetry'
import { INJECT_PRESETS, eventName } from './injectPresets'

const SPEEDS = [1, 10, 60, 600, 3600]
const SPEED_OPTIONS = SPEEDS.map((s) => ({ value: String(s), label: `×${s}` }))
const KINDS: EmergencyKind[] = ['depressurization', 'fire', 'toxic', 'equipment', 'medical']
// slider 0..1 -> speed 1..100000 (log scale)
const toSpeed = (x: number) => Math.round(10 ** (x * 5))
const fromSpeed = (s: number) => Math.log10(Math.max(1, s)) / 5

const debugEnabled = () => import.meta.env.DEV || new URLSearchParams(window.location.search).has('debug')

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="mb-5"><h3 className="mb-2 text-sm text-status-warning-foreground">{title}</h3>{children}</section>
}

export function DebugPanel() {
  const [open, setOpen] = useState(false)
  const cmd = useCommands()
  const st = useBackendStatus()
  const tick = useTick()
  const modules = useModuleList()
  const [kind, setKind] = useState<EmergencyKind>('fire')
  const [mod, setMod] = useState('hab')
  // While the slider is dragged it follows the pointer; otherwise it mirrors the backend speed (so the ×N buttons move it).
  const [drag, setDrag] = useState<number | null>(null)
  const [picked, setPicked] = useState<string[]>([])
  const [stopping, setStopping] = useState<string[]>([])
  if (!debugEnabled()) return null

  const presets = INJECT_PRESETS.map((p) => ({ value: p.label, label: p.label }))
  const faults = (tick?.active_faults ?? []).map((f) => ({ value: f, label: eventName(f) }))
  const inject = () => {
    for (const p of INJECT_PRESETS) if (picked.includes(p.label)) cmd.inject(p.make())
    setPicked([])
  }
  const stop = () => {
    for (const f of stopping) cmd.stopEvent(f)
    setStopping([])
  }

  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className="fixed bottom-3.5 right-3.5 z-30 rounded-control border border-dashed border-status-warning px-2.5 py-1.5 text-xs font-medium text-status-warning-foreground opacity-60 outline-none hover:opacity-100 focus-visible:opacity-100 focus-visible:ring-3 focus-visible:ring-ring/50" style={{ marginBottom: 'env(safe-area-inset-bottom)' }}>
        ⌥ Debug
      </button>
      <Sheet open={open} onClose={() => setOpen(false)} title="Debug" width={360} className="text-sm">
        <p className="mb-4 rounded-lg bg-status-warning-soft p-2 text-xs text-status-warning-foreground">Development and demo only. Not present in the operational build.</p>

        <Section title="Connection">
          <div className="mb-1.5 flex items-center gap-2">
            <StatusBadge status={st.connected ? 'ok' : 'crit'}>{st.connected ? 'Connected' : 'Disconnected'}</StatusBadge>
            <span className="truncate text-xs text-muted-foreground">{st.url}</span>
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
            <dt className="text-muted-foreground">Scenario</dt><dd className="truncate">{st.scenario ?? '—'}</dd>
            <dt className="text-muted-foreground">Speed</dt><dd>×{st.speed}{st.paused ? ' (paused)' : ''}</dd>
            <dt className="text-muted-foreground">Tick</dt><dd className="tabular-nums">{tick?.tick ?? '—'} · {tick ? Math.round(tick.t_sim_s) : '—'} s</dd>
          </dl>
        </Section>

        <Section title="Simulation control">
          <div className="mb-2 flex gap-2">
            <Button variant="outline" className="flex-1" onClick={() => (st.paused ? cmd.resume() : cmd.pause())}>{st.paused ? 'Resume' : 'Pause'}</Button>
            <Button variant="outline" className="flex-1" onClick={() => cmd.reset()}>Reset</Button>
          </div>
          <ToggleGroup joined className="w-full [&>button]:flex-1 [&>button]:px-0" value={String(st.speed)} onChange={(v) => cmd.setSpeed(Number(v))} options={SPEED_OPTIONS} />
          <input type="range" min={0} max={1} step={0.01} value={drag ?? fromSpeed(st.speed || 60)} className="mt-2 w-full accent-primary" aria-label="Speed"
            onChange={(e) => { const x = Number(e.target.value); setDrag(x); cmd.setSpeed(toSpeed(x)) }}
            onPointerUp={() => setDrag(null)} onKeyUp={() => setDrag(null)} onBlur={() => setDrag(null)} />
          <p className="text-xs text-muted-foreground">Simulated seconds per real second · ×{st.speed}</p>
        </Section>

        <Section title="Inject events">
          <ToggleGroupMulti value={picked} onChange={setPicked} options={presets} />
          <Button className="mt-2 w-full" variant="outline" disabled={picked.length === 0} onClick={inject}>
            {picked.length > 1 ? `Inject ${picked.length} events` : 'Inject event'}
          </Button>
        </Section>

        <Section title="Active events">
          {faults.length ? (
            <>
              <ToggleGroupMulti value={stopping} onChange={setStopping} options={faults} />
              <Button className="mt-2 w-full" variant="outline" disabled={stopping.length === 0} onClick={stop}>
                {stopping.length > 1 ? `Stop ${stopping.length} events` : 'Stop event'}
              </Button>
            </>
          ) : <span className="text-xs text-muted-foreground">None</span>}
        </Section>

        <Section title="Declare emergency">
          <ToggleGroup className="mb-2" value={kind} onChange={setKind} options={KINDS.map((k) => ({ value: k, label: k }))} />
          <div className="flex gap-2">
            <select value={mod} onChange={(e) => setMod(e.target.value)} aria-label="Module" className="h-8 min-w-0 flex-1 rounded-control border border-input bg-card px-2 text-sm">
              {(modules.length ? modules.map((m) => m.id) : ['hab']).map((m) => <option key={m}>{m}</option>)}
            </select>
            <Button variant="outline" onClick={() => cmd.declare(kind, mod)}>Declare</Button>
          </div>
        </Section>

        {st.commandError && <p className="rounded-lg bg-status-danger-soft p-2 text-status-danger-foreground">Error: {st.commandError}</p>}
      </Sheet>
    </>
  )
}
