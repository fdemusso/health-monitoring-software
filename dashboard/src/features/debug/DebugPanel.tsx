import { useState, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Sheet } from '@/components/ui/sheet'
import { ToggleGroup } from '@/components/ui/toggle-group'
import { crewIdentity } from '@/domain/crewConfig'
import { moduleName } from '@/domain/names'
import type { EmergencyKind } from '@/telemetry'
import { useBackendStatus, useCommands, useCrewList, useModuleList, useTick } from '@/telemetry/useTelemetry'
import { CREW_SCENARIOS, STATION_SCENARIOS, eventName, type Scenario } from './injectPresets'

/** The dashboard offers 1x to 60x: above that the engine cannot keep up (the server refuses more, see `ares3 serve --max-speed`). */
const SPEEDS = [1, 10, 30, 60]
const SPEED_OPTIONS = SPEEDS.map((s) => ({ value: String(s), label: `${s}×` }))
const ALARMS: { kind: EmergencyKind; label: string }[] = [
  { kind: 'fire', label: 'Fire' }, { kind: 'depressurization', label: 'Air leak' }, { kind: 'toxic', label: 'Toxic air' },
  { kind: 'equipment', label: 'Equipment' }, { kind: 'medical', label: 'Medical' },
]
/** The lifeboat and the spacewalk volume are not places where things break by themselves. */
const NOT_A_PLACE = new Set(['LIFEBOAT', 'EVA'])

const clock = (s: number) => `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="mb-6">
      <h3 className="text-sm font-medium text-status-warning-foreground">{title}</h3>
      {hint && <p className="mb-2 text-xs text-muted-foreground">{hint}</p>}
      <div className={hint ? '' : 'mt-2'}>{children}</div>
    </section>
  )
}

const SELECT = 'h-11 w-full rounded-control border border-input bg-card px-2 text-sm'

/** One tap, one situation: the title and what the app will show. */
function ScenarioButton({ s, onPick }: { s: Scenario; onPick: () => void }) {
  return (
    <button type="button" onClick={onPick} className="min-h-14 rounded-control border border-input px-3 py-2 text-left outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 active:bg-muted-strong">
      <span className="block text-sm font-medium">{s.label}</span>
      <span className="block text-xs text-muted-foreground">{s.hint}</span>
    </button>
  )
}

/**
 * Cheat menu: for whoever tries the platform, to create a situation and watch the app react. It never blocks the page behind it.
 * Dev builds, or `?debug` in the address.
 */
export function DebugPanel() {
  const [open, setOpen] = useState(false)
  const cmd = useCommands()
  const st = useBackendStatus()
  const tick = useTick()
  const crew = useCrewList()
  const places = useModuleList().filter((m) => !NOT_A_PLACE.has(m.id.toUpperCase()))
  const [place, setPlace] = useState('USL')
  const [person, setPerson] = useState('')

  const where = places.some((m) => m.id === place) ? place : places[0]?.id ?? ''
  const who = crew.some((n) => n.id === person) ? person : crew[0]?.id ?? ''
  const start = (s: Scenario) => cmd.inject(s.make(s.target === 'crew' ? who : where))
  const faults = tick?.active_faults ?? []

  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className="fixed bottom-3.5 right-3.5 z-30 rounded-control border border-status-warning bg-card px-3 py-2 text-sm font-medium text-status-warning-foreground outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50" style={{ marginBottom: 'env(safe-area-inset-bottom)' }}>
        ⌥ Scenarios
      </button>
      <Sheet open={open} onClose={() => setOpen(false)} title="Scenario menu" width={380} modeless className="text-sm">
        {!st.connected && <p className="mb-4 rounded-lg bg-status-danger-soft p-2 text-status-danger-foreground">Not connected to the simulation.</p>}
        {st.commandError && <p className="mb-4 rounded-lg bg-status-danger-soft p-2 text-status-danger-foreground">{st.commandError}</p>}

        <Section title="Time" hint={tick ? `Simulated time ${clock(tick.t_sim_s)} · runs ${st.speed}× faster than real time${st.paused ? ' · paused' : ''}` : undefined}>
          <ToggleGroup joined className="w-full [&>button]:flex-1 [&>button]:px-0" value={String(st.speed)} onChange={(v) => cmd.setSpeed(Number(v))} options={SPEED_OPTIONS} />
          <div className="mt-2 flex gap-2">
            <Button variant="outline" className="flex-1" onClick={() => (st.paused ? cmd.resume() : cmd.pause())}>{st.paused ? 'Resume' : 'Pause'}</Button>
            <Button variant="outline" className="flex-1" onClick={() => cmd.reset()}>Start over</Button>
          </div>
        </Section>

        <Section title="Station" hint="Pick a place, then tap what happens there.">
          <select value={where} onChange={(e) => setPlace(e.target.value)} aria-label="Place" className={`${SELECT} mb-2`}>
            {places.map((m) => <option key={m.id} value={m.id}>{moduleName(m.id)}</option>)}
          </select>
          <div className="grid grid-cols-2 gap-2">
            {STATION_SCENARIOS.map((s) => <ScenarioButton key={s.key} s={s} onPick={() => start(s)} />)}
          </div>
        </Section>

        <Section title="Crew" hint="Pick a person, then tap what happens to them.">
          <select value={who} onChange={(e) => setPerson(e.target.value)} aria-label="Person" className={`${SELECT} mb-2`}>
            {crew.map((n) => <option key={n.id} value={n.id}>{crewIdentity(n.id).person} · {crewIdentity(n.id).name}</option>)}
          </select>
          <div className="grid grid-cols-2 gap-2">
            {CREW_SCENARIOS.map((s) => <ScenarioButton key={s.key} s={s} onPick={() => start(s)} />)}
          </div>
        </Section>

        <Section title="Happening now">
          {faults.length ? (
            <ul className="space-y-1">
              {faults.map((f) => (
                <li key={f} className="flex items-center justify-between gap-2 rounded-control bg-muted/50 py-1 pl-3 pr-1">
                  <span className="min-w-0 truncate">{eventName(f)}</span>
                  <Button variant="ghost" size="sm" onClick={() => cmd.stopEvent(f)}>Stop</Button>
                </li>
              ))}
            </ul>
          ) : <span className="text-xs text-muted-foreground">Nothing. The station is nominal.</span>}
        </Section>

        <Section title="Sound the alarm" hint="Only the alarm, without a real fault: to see how the crew responds.">
          <div className="flex flex-wrap gap-1">
            {ALARMS.map((a) => <Button key={a.kind} variant="outline" onClick={() => cmd.declare(a.kind, where)}>{a.label}</Button>)}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">In: {where ? moduleName(where) : '—'}</p>
        </Section>
      </Sheet>
    </>
  )
}
