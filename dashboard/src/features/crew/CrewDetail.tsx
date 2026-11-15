import { ArrowLeft } from 'lucide-react'
import { useMemo, useRef } from 'react'
import { CrewChip } from '@/components/CrewChip'
import { Sparkline } from '@/components/Sparkline'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { crewIdentity } from '@/domain/crewConfig'
import { activityLabel, phaseLabel } from '@/domain/emergencyText'
import { crewStatus, statusLabel, statusText, vitalStatus, type Status } from '@/domain/status'
import { fmt0, fmt1, ppco2Mmhg } from '@/domain/units'
import type { NPCState, SimulationTick } from '@/telemetry'
import type { CrewSample } from '@/telemetry/store'
import { useCrewHistory, useModuleHistory } from '@/telemetry/useTelemetry'
import { HologramCallouts } from './HologramCallouts'
import { useElementWidth } from './CrewColumn'
import { HologramFrame, useOrganAnchors } from './HologramFrame'
import { ResponsePanel } from './ResponsePanel'
import { limitStatus, ENV_METRICS } from '@/domain/limits'

function Field({ label, value }: { label: string; value: string }) {
  return <div><div className="lbl">{label}</div><div className="mt-0.5 text-base">{value}</div></div>
}

function Trend({ title, value, unit, status, values }: { title: string; value: string; unit: string; status: Status; values: number[] }) {
  return (
    <div className="min-w-0 border-l border-white/10 pl-4 first:border-l-0 first:pl-0">
      <div className="lbl truncate">{title}</div>
      <div className={`num text-[34px] leading-tight ${status !== 'ok' ? statusText[status] : ''}`}>{value}<span className="ml-1 text-sm text-muted-foreground">{unit}</span></div>
      <Sparkline values={values} status={status} />
    </div>
  )
}

const series = (h: CrewSample[] | undefined, k: keyof CrewSample) => (h ?? []).map((s) => s[k]).filter((x): x is number => typeof x === 'number')

export function CrewDetail({ npc, tick, onBack }: { npc: NPCState; tick: SimulationTick; onBack: () => void }) {
  const id = crewIdentity(npc.id)
  const st = crewStatus(npc, tick.emergencies)
  const hist = useCrewHistory(npc.id)
  const mod = tick.modules[npc.module_id]
  const mhist = useModuleHistory(npc.module_id)
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
      <div>
        <div className="mb-4 flex flex-wrap items-center gap-x-8 gap-y-3">
          <Button variant="outline" size="sm" onClick={onBack}><ArrowLeft size={16} /> Equipaggio</Button>
          <div>
            <CrewChip id={npc.id} large />
            <div className="mt-1.5 text-center text-xs text-muted-foreground">{id.name}</div>
          </div>
          <Field label="Modulo" value={npc.module_id.toUpperCase()} />
          <Field label={phase ? 'Risposta all’emergenza' : 'Attività'} value={phase ?? activityLabel(npc.activity)} />
          <Badge tone={st} className="ml-auto">{statusLabel[st]}</Badge>
        </div>
        <div className="grid grid-cols-4 gap-4">
          <Trend title={`FC di ${id.label}`} value={fmt0(v.hr)} unit="bpm" status={vitalStatus('hr', v.hr, npc.activity)} values={series(hist, 'hr')} />
          <Trend title={`SpO₂ di ${id.label}`} value={fmt0(v.spo2)} unit="%" status={vitalStatus('spo2', v.spo2)} values={series(hist, 'spo2')} />
          <Trend title={`Temp. core di ${id.label}`} value={fmt1(v.core_temp_c)} unit="°C" status={vitalStatus('core_temp_c', v.core_temp_c)} values={series(hist, 'core')} />
          {co
            ? <Trend title={`COHb di ${id.label}`} value={fmt1(v.cohb_pct)} unit="%" status={vitalStatus('cohb_pct', v.cohb_pct)} values={ctx} />
            : <Trend title={`ppCO₂ in ${npc.module_id.toUpperCase()}`} value={mod ? fmt1(ppco2Mmhg(mod)) : '—'} unit="mmHg" status={mod ? limitStatus(ENV_METRICS.ppco2, ppco2Mmhg(mod)) : 'ok'} values={ctx} />}
        </div>
      </div>
      <div className="grid grid-cols-[1fr_290px] gap-[18px] animate-in fade-in zoom-in-95 duration-150">
        <div ref={stageRef} className="relative min-w-0" style={{ height: H }}>
          <HologramFrame npc={npc} tick={tick} width={W} color={id.color} />
          <HologramCallouts npc={npc} anchors={anchors} width={stageW} height={H} />
        </div>
        <ResponsePanel tick={tick} crewId={npc.id} emergency={emergency} />
      </div>
    </>
  )
}
