import { ArrowLeft, ClipboardCheck } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { Dialog } from '@/components/ui/dialog'
import { Sparkline } from '@/components/Sparkline'
import { StatusBadge } from '@/components/ui/status-badge'
import { Button } from '@/components/ui/button'
import { moduleName } from '@/domain/names'
import { crewIdentity } from '@/domain/crewConfig'
import { activityLabel, phaseLabel } from '@/domain/emergencyText'
import { crewStatus, statusLabel, statusText, vitalStatus, type Status } from '@/domain/status'
import { fmt0, fmt1, ppco2Mmhg } from '@/domain/units'
import type { NPCState, SimulationTick } from '@/telemetry'
import type { CrewSample } from '@/telemetry/store'
import { useElementWidth } from '@/lib/useElementWidth'
import { useCrewHistory, useModuleHistory } from '@/telemetry/useTelemetry'
import { HologramCallouts } from './HologramCallouts'
import { HologramFrame, useOrganAnchors } from './HologramFrame'
import { ResponsePanel } from './ResponsePanel'
import { limitStatus, ENV_METRICS } from '@/domain/limits'

function Field({ label, value }: { label: string; value: string }) {
  return <div><div className="lbl">{label}</div><div className="mt-0.5 text-base font-medium">{value}</div></div>
}

function Trend({ title, value, unit, status, values }: { title: string; value: string; unit: string; status: Status; values: number[] }) {
  return (
    <div className="min-w-0 border-l border-border pl-4 first:border-l-0 first:pl-0">
      <div className="lbl truncate">{title}</div>
      <div className={`num text-5xl leading-tight ${status !== 'ok' ? statusText[status] : ''}`}>{value}<span className="ml-1 font-sans text-sm font-normal text-muted-foreground">{unit}</span></div>
      <Sparkline values={values} status={status} />
    </div>
  )
}

/** The last hour of a vital (one sample per 10 s) for a sparkline. */
const series = (h: CrewSample[] | undefined, k: keyof CrewSample) => (h ?? []).slice(-360).map((s) => s[k]).filter((x): x is number => typeof x === 'number')

export function CrewDetail({ npc, tick, onBack }: { npc: NPCState; tick: SimulationTick; onBack: () => void }) {
  const id = crewIdentity(npc.id)
  const st = crewStatus(npc, tick.emergencies)
  const hist = useCrewHistory(npc.id)
  const mod = tick.modules[npc.module_id]
  const mhist = useModuleHistory(npc.module_id)
  const [routineOpen, setRoutineOpen] = useState(false)
  const stageRef = useRef<HTMLDivElement>(null)
  const [, stageW] = useElementWidth(stageRef)
  const W = 280
  const H = Math.round(W * 1.78)
  const anchors = useOrganAnchors(stageRef, [W, stageW, npc.sex])
  const phase = phaseLabel(npc.response_phase)
  const v = npc.vitals
  const co = mod && (mod.co_ppm > 0.5 || (v.cohb_pct ?? 0) >= 2)
  const ctx = useMemo(() => (co ? series(hist, 'cohb') : (mhist ?? []).map((s) => s.ppco2)), [co, hist, mhist])
  const emergency = tick.emergencies.find((e) => e.state !== 'cleared' && (e.subject === npc.id || (!e.subject && e.module_id === npc.module_id)))
  return (
    <>
      <div data-void>
        <div data-void className="mb-4 flex flex-wrap items-center gap-x-8 gap-y-3">
          <Button variant="outline" onClick={onBack}><ArrowLeft size={16} /> Crew</Button>
          <div>
            <h2 className="flex items-center gap-2 font-heading text-2xl font-bold"><span aria-hidden className="size-3 rounded-full" style={{ background: id.color }} />{id.person}</h2>
            <div className="mt-0.5 text-xs text-muted-foreground">{id.name}</div>
          </div>
          <Field label="Location" value={moduleName(npc.module_id)} />
          <Field label={phase ? 'Emergency response' : 'Activity'} value={phase ?? activityLabel(npc.activity)} />
          <StatusBadge status={st} className="ml-auto">{statusLabel[st]}</StatusBadge>
        </div>
        <div data-void className="grid grid-cols-4 gap-4">
          <Trend title={`${id.first}: heart rate`} value={fmt0(v.hr)} unit="bpm" status={vitalStatus('hr', v.hr, npc.activity)} values={series(hist, 'hr')} />
          <Trend title={`${id.first}: blood oxygen`} value={fmt0(v.spo2)} unit="%" status={vitalStatus('spo2', v.spo2)} values={series(hist, 'spo2')} />
          <Trend title={`${id.first}: body temperature`} value={fmt1(v.core_temp_c)} unit="°C" status={vitalStatus('core_temp_c', v.core_temp_c)} values={series(hist, 'core')} />
          {co
            ? <Trend title={`${id.first}: carbon monoxide in blood`} value={fmt1(v.cohb_pct)} unit="%" status={vitalStatus('cohb_pct', v.cohb_pct)} values={ctx} />
            : <Trend title={`Carbon dioxide in ${moduleName(npc.module_id)}`} value={mod ? fmt1(ppco2Mmhg(mod)) : '—'} unit="mmHg" status={mod ? limitStatus(ENV_METRICS.ppco2, ppco2Mmhg(mod)) : 'ok'} values={ctx} />}
        </div>
      </div>
      <div data-void className="grid grid-cols-[290px_1fr_290px] gap-[18px] animate-in fade-in-0 duration-(--duration-enter)">
        {/* Columns 1 and 3 are the same width, so the figure (column 2) sits at the centre of the page. */}
        <div ref={stageRef} data-void className="relative col-start-2 min-w-0" style={{ height: H }}>
          <HologramFrame npc={npc} tick={tick} width={W} color={id.color} />
          <HologramCallouts npc={npc} anchors={anchors} width={stageW} height={H} />
        </div>
        {emergency ? (
          <ResponsePanel className="col-start-3" tick={tick} crewId={npc.id} emergency={emergency} />
        ) : (
          <div className="col-start-3 min-w-0">
            <Button variant="outline" size="lg" className="w-full justify-start gap-2" onClick={() => setRoutineOpen(true)}>
              <ClipboardCheck size={18} /> Routine check
            </Button>
            <Dialog open={routineOpen} onClose={() => setRoutineOpen(false)} title="Routine check" width={400}>
              <ResponsePanel tick={tick} crewId={npc.id} emergency={null} />
            </Dialog>
          </div>
        )}
      </div>
    </>
  )
}
