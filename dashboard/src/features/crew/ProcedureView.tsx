import { Check, CircleAlert, Minus, PhoneCall, X } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { StatusBadge, type StatusTone } from '@/components/ui/status-badge'
import { crewIdentity } from '@/domain/crewConfig'
import { seenLines } from '@/domain/emergencyText'
import { moduleName } from '@/domain/names'
import { chooseProcedure, fillText, isMedical, procedureOf } from '@/domain/procedures'
import { fmt0, fmt1, fmtClock } from '@/domain/units'
import { cn } from '@/lib/utils'
import type { Emergency, ProcedureSpec, ProcedureState, ProcedureStepState, SimulationTick } from '@/telemetry'
import { useCatalog, useCommands } from '@/telemetry/useTelemetry'

const ALERT_TONE: Record<Emergency['alert_class'], StatusTone> = { emergency: 'crit', warning: 'warn', caution: 'warn', advisory: 'info' }

/** Fixed notice of every medical procedure (docs/monitor-ui.md): always visible, never dismissible. */
function MedicalNotice() {
  return (
    <p role="note" className="rounded-lg border border-status-warning bg-status-warning-soft p-3 text-xs text-status-warning-foreground">
      Simulation checklist, NOT medical advice. The steps are reconstructed from public sources and have not been reviewed by a flight surgeon.
      In a real emergency follow the ISS Medical Checklist and the instructions of the flight surgeon.
    </p>
  )
}

const who = (by: string | null) => (by == null ? 'automatic' : crewIdentity(by).first)

function StepMark({ status, index }: { status: ProcedureStepState['status']; index: number }) {
  const base = 'mt-0.5 grid size-6 shrink-0 place-items-center rounded-full text-xs'
  if (status === 'done') return <span className={cn(base, 'bg-status-live text-signal-on')}><Check size={14} aria-label="Done" /></span>
  if (status === 'failed') return <span className={cn(base, 'bg-status-danger text-signal-on')}><X size={14} aria-label="Did not work" /></span>
  if (status === 'skipped') return <span className={cn(base, 'bg-muted text-muted-foreground')}><Minus size={14} aria-label="Skipped" /></span>
  return <span className={cn(base, status === 'active' ? 'bg-foreground text-background' : 'bg-muted-strong')}>{index + 1}</span>
}

/** What the person can do about the active step of a running procedure. */
function StepControls({ proc, step, tick }: { proc: ProcedureState; step: ProcedureStepState; tick: SimulationTick }) {
  const cmd = useCommands()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const ack = async (answer?: 'yes' | 'no') => {
    setBusy(true); setError(null)
    const r = await cmd.ackStep(proc.id, step.id, answer)
    if (!r.ok) setError(r.error ?? 'rejected')
    setBusy(false)
  }
  if (step.kind === 'instruction') return <><Button className="mt-2 w-full" disabled={busy} onClick={() => ack()}>Done</Button>{error && <Err text={error} />}</>
  if (step.kind === 'question') {
    return (
      <>
        <div className="mt-2 flex gap-2">
          <Button className="flex-1" disabled={busy} onClick={() => ack('yes')}>Yes</Button>
          <Button className="flex-1" variant="outline" disabled={busy} onClick={() => ack('no')}>No</Button>
        </div>
        {error && <Err text={error} />}
      </>
    )
  }
  if (step.kind === 'check') {
    const left = step.deadline_s == null ? null : step.deadline_s - tick.t_sim_s
    return <p className="mt-1 text-xs text-muted-foreground tabular-nums">Checking the readings{left != null && ` · ${fmtClock(left)} left`}</p>
  }
  if (step.kind === 'action') return <p className="mt-1 text-xs text-muted-foreground">Waiting for the action to be approved or carried out (see “Awaiting confirmation”)</p>
  return null
}
const Err = ({ text }: { text: string }) => <p className="mt-1 text-xs text-status-danger-foreground">{text}</p>

function Steps({ steps, current, render }: { steps: { id: string; status: ProcedureStepState['status']; text: string; kind: string; by?: string | null; answer?: string | null }[]; current: string | null; render?: (id: string) => React.ReactNode }) {
  return (
    <ol className="space-y-2">
      {steps.map((s, i) => {
        const active = s.status === 'active' || (current === s.id && s.status === 'pending')
        return (
          <li key={s.id} className={cn('flex gap-3 rounded-lg border p-3',
            s.status === 'active' ? 'border-foreground bg-card' : s.status === 'failed' ? 'border-status-danger bg-status-danger-soft' : s.status === 'done' ? 'border-border bg-status-live-soft' : 'border-transparent',
            (s.status === 'skipped' || (s.status === 'pending' && !active)) && 'text-muted-foreground')}>
            <StepMark status={s.status} index={i} />
            <div className="min-w-0 flex-1">
              <div className={cn('text-sm', s.status === 'active' ? 'font-medium' : s.status === 'skipped' && 'line-through')}>{s.text}</div>
              {s.status === 'done' && (s.by !== undefined || s.answer) && (
                <div className="mt-0.5 text-xs text-muted-foreground">{s.by !== undefined && `by ${who(s.by)}`}{s.answer && ` · answered ${s.answer}`}</div>
              )}
              {s.status === 'active' && render?.(s.id)}
            </div>
          </li>
        )
      })}
    </ol>
  )
}

/** A procedure the backend is running (or just finished): the checklist, with the control of the active step. */
function LiveProcedure({ tick, proc, emergency, compact }: { tick: SimulationTick; proc: ProcedureState; emergency: Emergency; compact?: boolean }) {
  const counted = proc.steps.filter((s) => s.status !== 'skipped')
  const done = counted.filter((s) => s.status === 'done').length
  const subject = emergency.subject ? tick.npcs[emergency.subject] : undefined
  const escalation = proc.steps.find((s) => s.kind === 'escalate' && s.status !== 'pending' && s.status !== 'skipped')
  return (
    <div className="space-y-3">
      {isMedical(emergency.kind) && <MedicalNotice />}
      {!compact && <Header emergency={emergency} title={proc.title} />}
      {proc.status === 'escalated' && escalation ? (
        <div role="alert" className="space-y-3 rounded-lg border-2 border-status-danger bg-status-danger-soft p-4">
          <div className="flex items-start gap-2 font-medium text-status-danger-foreground"><PhoneCall className="mt-0.5 size-5 shrink-0" aria-hidden />{escalation.text}</div>
          <Summary title="Done" steps={proc.steps.filter((s) => s.status === 'done' && s.kind !== 'escalate')} />
          <Summary title="Did not work (report it to Earth)" steps={proc.steps.filter((s) => s.status === 'failed')} />
          {subject && (
            <p className="text-xs tabular-nums text-status-danger-foreground">
              {crewIdentity(subject.id).first} now: heart {fmt0(subject.vitals.hr)} bpm · blood oxygen {fmt0(subject.vitals.spo2)} % · body {fmt1(subject.vitals.core_temp_c)} °C
            </p>
          )}
        </div>
      ) : (
        <>
          <Progress value={counted.length ? (done / counted.length) * 100 : 0} aria-label="Procedure progress" />
          <p className="text-xs text-muted-foreground">
            {proc.status === 'done' ? 'Procedure completed' : proc.status === 'closed' ? 'The emergency is over: procedure closed' : `${done} of ${counted.length} steps done`}
          </p>
          <Steps steps={proc.steps} current={proc.current} render={(id) => { const s = proc.steps.find((x) => x.id === id); return s ? <StepControls proc={proc} step={s} tick={tick} /> : null }} />
        </>
      )}
    </div>
  )
}

function Summary({ title, steps }: { title: string; steps: ProcedureStepState[] }) {
  if (!steps.length) return null
  return (
    <div className="text-xs text-status-danger-foreground">
      <div className="font-medium">{title}</div>
      <ul className="mt-1 list-disc space-y-0.5 pl-4">{steps.map((s) => <li key={s.id}>{s.text}</li>)}</ul>
    </div>
  )
}

function Header({ emergency, title }: { emergency: Emergency; title: string }) {
  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-heading text-xl font-bold">{title}</h3>
        <StatusBadge status={ALERT_TONE[emergency.alert_class]}>{emergency.alert_class}</StatusBadge>
      </div>
      <p className="mt-0.5 text-xs text-muted-foreground">{emergency.subject ? `${crewIdentity(emergency.subject).first} · ` : ''}{moduleName(emergency.module_id)}</p>
      {seenLines(emergency, 4).length > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">{seenLines(emergency, 4).map((e) => <li key={e}>{e}</li>)}</ul>
      )}
    </div>
  )
}

/** A procedure of the catalog, read-only: what the backend will run for an emergency not yet confirmed, or any protocol of the library. */
export function PreviewProcedure({ spec, emergency, note }: { spec: ProcedureSpec; emergency?: Emergency; note?: string }) {
  return (
    <div className="space-y-3">
      {isMedical(spec.emergency) && <MedicalNotice />}
      <h3 className="font-heading text-xl font-bold">{fillText(spec.title, emergency)}</h3>
      {note && <p className="flex items-start gap-2 rounded-lg bg-muted p-3 text-xs text-muted-foreground"><CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />{note}</p>}
      <Steps current={null} steps={spec.steps.map((s) => ({ id: s.id, status: 'pending' as const, text: fillText(s.text, emergency), kind: s.kind }))} />
    </div>
  )
}

/**
 * The protocol for an emergency: the checklist the backend is running if there is one, else the one it will start once the monitor
 * confirms the emergency (proposed ahead of time), else a plain "no protocol" message.
 */
export function EmergencyProtocol({ tick, emergency, compact }: { tick: SimulationTick; emergency: Emergency; compact?: boolean }) {
  const catalog = useCatalog()
  const proc = procedureOf(tick, emergency)
  if (proc) return <LiveProcedure tick={tick} proc={proc} emergency={emergency} compact={compact} />
  const spec = chooseProcedure(catalog, emergency)
  if (!spec) {
    return <p className="text-sm text-muted-foreground">No crew checklist for this alert: the station's automatic response handles it (confirm the actions above, if any) and the crew acts as shown below.</p>
  }
  return <PreviewProcedure spec={spec} emergency={emergency} note={emergency.state === 'suspected' ? 'Proposed: the monitor is still verifying this emergency. The checklist starts by itself when it is confirmed.' : 'Proposed protocol: it starts when the monitor opens the response.'} />
}
