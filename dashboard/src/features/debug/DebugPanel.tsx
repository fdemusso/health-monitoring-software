import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Sheet } from '@/components/ui/sheet'
import type { EmergencyKind } from '@/telemetry'
import { useBackendStatus, useCommands, useModuleList, useTick } from '@/telemetry/useTelemetry'
import { INJECT_PRESETS } from './injectPresets'

const SPEEDS = [1, 10, 60, 600, 3600]
const KINDS: EmergencyKind[] = ['depressurization', 'fire', 'toxic', 'equipment', 'medical']
// slider 0..1 -> speed 1..100000 (log scale)
const toSpeed = (x: number) => Math.round(10 ** (x * 5))
const fromSpeed = (s: number) => Math.log10(Math.max(1, s)) / 5

export const debugEnabled = () => import.meta.env.DEV || new URLSearchParams(window.location.search).has('debug')

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="mb-5"><h3 className="mb-2 text-[10px] tracking-widest text-warn">{title.toUpperCase()}</h3>{children}</section>
}

export function DebugPanel() {
  const [open, setOpen] = useState(false)
  const cmd = useCommands()
  const st = useBackendStatus()
  const tick = useTick()
  const modules = useModuleList()
  const [kind, setKind] = useState<EmergencyKind>('fire')
  const [mod, setMod] = useState('hab')
  if (!debugEnabled()) return null

  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className="fixed bottom-3.5 right-3.5 z-30 rounded-md border border-dashed border-warn px-2.5 py-1.5 font-mono text-[10px] tracking-widest text-warn opacity-50 hover:opacity-100" style={{ marginBottom: 'env(safe-area-inset-bottom)' }}>
        ⌥ DEBUG
      </button>
      <Sheet open={open} onClose={() => setOpen(false)} title="Debug" width={360} className="border-l-dashed border-warn/60 font-mono text-xs">
        <p className="mb-4 rounded-md border border-warn/40 bg-warn/10 p-2 text-warn">Solo sviluppo e demo. Non esiste nella build operativa.</p>

        <Section title="Connessione">
          <div className="space-y-0.5 text-muted-foreground">
            <div>stato: {st.connected ? 'collegato' : 'scollegato'}</div>
            <div>url: {st.url}</div>
            <div>scenario: {st.scenario ?? '—'}</div>
            <div>velocità: ×{st.speed}{st.paused ? ' (pausa)' : ''}</div>
            <div>tick: {tick?.tick ?? '—'} · t_sim: {tick ? Math.round(tick.t_sim_s) : '—'} s</div>
          </div>
        </Section>

        <Section title="Controllo simulazione">
          <div className="mb-2 flex gap-2">
            <Button size="sm" variant="outline" onClick={() => (st.paused ? cmd.resume() : cmd.pause())}>{st.paused ? 'Riprendi' : 'Pausa'}</Button>
            <Button size="sm" variant="outline" onClick={() => cmd.reset()}>Reset</Button>
          </div>
          <div className="mb-2 flex flex-wrap gap-1.5">
            {SPEEDS.map((s) => <Button key={s} size="sm" variant={st.speed === s ? 'default' : 'outline'} onClick={() => cmd.setSpeed(s)}>×{s}</Button>)}
          </div>
          <input type="range" min={0} max={1} step={0.01} defaultValue={fromSpeed(st.speed || 60)} className="w-full" aria-label="Velocità"
            onChange={(e) => cmd.setSpeed(toSpeed(Number(e.target.value)))} />
          <p className="mt-1 text-muted-foreground">velocità = secondi simulati per secondo reale</p>
        </Section>

        <Section title="Inietta evento">
          <div className="flex flex-wrap gap-1.5">
            {INJECT_PRESETS.map((p) => <Button key={p.label} size="sm" variant="outline" onClick={() => cmd.inject(p.make())}>{p.label}</Button>)}
          </div>
        </Section>

        <Section title="Eventi attivi">
          {tick?.active_faults.length ? tick.active_faults.map((f) => (
            <div key={f} className="mb-1 flex items-center justify-between gap-2">
              <span className="truncate">{f}</span>
              <Button size="sm" variant="outline" onClick={() => cmd.stopEvent(f)}>Stop</Button>
            </div>
          )) : <span className="text-muted-foreground">nessuno</span>}
        </Section>

        <Section title="Dichiara emergenza">
          <div className="flex gap-2">
            <select value={kind} onChange={(e) => setKind(e.target.value as EmergencyKind)} className="h-9 flex-1 rounded-md border border-white/20 bg-card px-2">
              {KINDS.map((k) => <option key={k}>{k}</option>)}
            </select>
            <select value={mod} onChange={(e) => setMod(e.target.value)} className="h-9 flex-1 rounded-md border border-white/20 bg-card px-2">
              {(modules.length ? modules.map((m) => m.id) : ['hab']).map((m) => <option key={m}>{m}</option>)}
            </select>
            <Button size="sm" onClick={() => cmd.declare(kind, mod)}>Dichiara</Button>
          </div>
        </Section>

        {st.commandError && <p className="rounded-md border border-crit/50 bg-crit/10 p-2 text-crit">Errore: {st.commandError}</p>}
      </Sheet>
    </>
  )
}
