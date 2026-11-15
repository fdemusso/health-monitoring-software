import { useMemo, type ReactNode } from 'react'
import { Sparkline } from '@/components/Sparkline'
import { StatusBadge } from '@/components/ui/status-badge'
import { crewIdentity } from '@/domain/crewConfig'
import { activityLabel, phaseLabel } from '@/domain/emergencyText'
import { effortLabel, moduleName, sleepLabel } from '@/domain/names'
import { crewStatus, statusLabel, statusText, vitalStatus, type Status } from '@/domain/status'
import { fmt0, fmt1 } from '@/domain/units'
import { useUiScale } from '@/lib/useUiScale'
import type { NPCState, SimulationTick } from '@/telemetry'
import type { CrewSample } from '@/telemetry/store'
import { useCrewHistory } from '@/telemetry/useTelemetry'
import { HologramFrame } from './HologramFrame'
import { ResponsePanel } from './ResponsePanel'

/** The last hour of a quantity (one sample per 10 s) for a sparkline. */
const series = (h: CrewSample[] | undefined, k: keyof CrewSample) => (h ?? []).slice(-360).map((s) => s[k]).filter((x): x is number => typeof x === 'number')

function Group({ title, children }: { title: string; children: ReactNode }) {
  return <section aria-label={title} className="min-w-0 space-y-3"><h3 className="lbl">{title}</h3>{children}</section>
}

/** One quantity: label, big value, optional note and optional trend. */
function Row({ label, value, unit, note, status = 'ok', values }: { label: string; value: string; unit?: string; note?: string; status?: Status; values?: number[] }) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm text-muted-foreground">{label}</span>
        <span className={`num text-2xl ${status !== 'ok' ? statusText[status] : ''}`}>{value}{unit && <span className="ml-1 font-sans text-xs font-normal text-muted-foreground">{unit}</span>}</span>
      </div>
      {note && <div className="text-xs text-muted-foreground">{note}</div>}
      {values && values.length > 1 && <div className="mt-1"><Sparkline values={values} status={status} height={26} /></div>}
    </div>
  )
}

/** Everything a wearable reads, in one card: vitals, temperatures, effort. */
function ReadingsCard({ npc, hist }: { npc: NPCState; hist?: CrewSample[] }) {
  const v = npc.vitals
  const af = (v.rhythm ?? 0) >= 0.5
  return (
    <div className="grid min-w-0 grid-cols-2 gap-x-6 gap-y-4 rounded-lg border border-border bg-card p-4">
      <Group title="Heart and lungs">
        <Row label="Heart rate" value={fmt0(v.hr)} unit="bpm" status={vitalStatus('hr', v.hr, npc.activity)} values={series(hist, 'hr')} />
        <Row label="Blood oxygen" value={fmt0(v.spo2)} unit="%" status={vitalStatus('spo2', v.spo2)} values={series(hist, 'spo2')} />
        <Row label="Breathing rate" value={fmt0(v.resp_rate)} unit="/min" status={vitalStatus('resp_rate', v.resp_rate)} values={series(hist, 'resp')} />
        <Row label="Rhythm" value={af ? 'Irregular' : 'Regular'} status={af ? 'crit' : 'ok'} />
      </Group>
      <Group title="Temperature and recovery">
        <Row label="Body temperature" value={fmt1(v.core_temp_c)} unit="°C" status={vitalStatus('core_temp_c', v.core_temp_c)} values={series(hist, 'core')} />
        <Row label="Skin temperature" value={fmt1(v.skin_temp_c)} unit="°C" values={series(hist, 'skin')} />
        <Row label="Heart-rate variability" value={fmt0(v.hrv_rmssd)} unit="ms" values={series(hist, 'hrv')} />
        <Row label="Sleep" value={sleepLabel(v.sleep_stage)} />
      </Group>
      <div className="col-span-2 border-t border-border pt-4">
        <Group title="Effort">
          <div className="grid grid-cols-2 gap-x-6">
            <Row label={effortLabel(npc.met)} value={fmt1(npc.met)} unit="MET" />
            <Row label="Oxygen uptake" value={fmt1(npc.vo2_l_min)} unit="L/min" />
          </div>
        </Group>
      </div>
    </div>
  )
}

/** Content of the crew popover: the body on the left, one card with everything a wearable measures on the right. */
export function CrewDetail({ npc, tick }: { npc: NPCState; tick: SimulationTick }) {
  const id = crewIdentity(npc.id)
  const st = crewStatus(npc, tick.emergencies)
  const hist = useCrewHistory(npc.id)
  const s = useUiScale()
  const W = Math.round(230 * s)
  const H = Math.round(W * 1.78)
  const phase = phaseLabel(npc.response_phase)
  const emergency = useMemo(() => tick.emergencies.find((e) => e.state !== 'cleared' && (e.subject === npc.id || (!e.subject && e.module_id === npc.module_id))), [tick.emergencies, npc.id, npc.module_id])
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <StatusBadge status={st}>{statusLabel[st]}</StatusBadge>
        <span className="text-sm text-muted-foreground">{moduleName(npc.module_id)} · {phase ?? activityLabel(npc.activity)}</span>
      </div>
      <div className="grid grid-cols-[auto_1fr] items-start gap-6">
        <div className="relative shrink-0" style={{ width: W, height: H }}><HologramFrame npc={npc} tick={tick} width={W} color={id.color} /></div>
        <ReadingsCard npc={npc} hist={hist} />
      </div>
      {emergency && <ResponsePanel tick={tick} emergency={emergency} />}
    </div>
  )
}
