import { BodyHologram } from '@/components/BodyHologram'
import { CornerBrackets } from '@/components/CornerBrackets'
import { CrewChip, ModuleChip } from '@/components/CrewChip'
import { StatusDot } from '@/components/StatusDot'
import { Button } from '@/components/ui/button'
import { useUi } from '@/app/ui-context'
import { sexToHologram, sortCrewIds } from '@/domain/crewConfig'
import { emergencyTitle, keyNumbers } from '@/domain/emergencyText'
import { organAdapter } from '@/domain/organAdapter'
import { crewStatus, isCriticalConfirmed, primaryEmergency, statusColor, type Status } from '@/domain/status'
import { fmtClock } from '@/domain/units'
import { cn } from '@/lib/utils'
import type { Emergency, SimulationTick } from '@/telemetry'
import { useMemo } from 'react'

function MiniHolo({ tick, id }: { tick: SimulationTick; id: string }) {
  const npc = tick.npcs[id]
  const organs = useMemo(() => (npc ? organAdapter.toOrganVitals(npc, tick.modules[npc.module_id], tick) : {}), [npc, tick])
  if (!npc) return null
  return <BodyHologram sex={sexToHologram(npc.sex)} organs={organs} size={110} showBase={false} />
}

export function AlertBanner({ tick }: { tick: SimulationTick }) {
  const ui = useUi()
  const { primary, others } = primaryEmergency(tick.emergencies)
  const crewList = sortCrewIds(Object.keys(tick.npcs))
  const nonOk = crewList.filter((id) => crewStatus(tick.npcs[id], tick.emergencies) !== 'ok')
  const pending = tick.pending_actions.length

  // Nominal: compact banner.
  if (!primary && nonOk.length === 0) {
    return (
      <div className="relative flex h-[90px] items-center gap-5 rounded-3xl border bg-card/40 px-7">
        <CornerBrackets />
        <StatusDot status="ok" className="size-3" />
        <span className="text-[26px] font-light tracking-tight">Equipaggio stabile</span>
        <div className="ml-auto flex gap-2">{crewList.map((id) => <CrewChip key={id} id={id} />)}</div>
      </div>
    )
  }

  // Fallback: vitals out of range but the monitor knows nothing.
  if (!primary) {
    const crit = nonOk.some((id) => crewStatus(tick.npcs[id], tick.emergencies) === 'crit')
    return <Frame level={crit ? 'crit' : 'warn'} pulse={false}>
      <Label level={crit ? 'crit' : 'warn'} text="Parametri fuori range" />
      <h1 className="mt-2 text-[36px] font-light leading-none tracking-tight">Parametri fuori range</h1>
      <div className="mt-4 flex gap-2">{nonOk.map((id) => <CrewChip key={id} id={id} />)}</div>
      <Button className="mt-5" variant="outline" onClick={() => ui.openCrew(nonOk[0])}>Apri dettaglio →</Button>
    </Frame>
  }

  const critical = isCriticalConfirmed(primary)
  const level: Status = primary.severity === 'critical' && primary.state === 'confirmed' ? 'crit' : 'warn'
  const suspected = primary.state === 'suspected'
  const title = (suspected ? 'Possibile ' : '') + lowerFirst(emergencyTitle(primary), suspected)
  const nums = keyNumbers(primary, tick)
  const mod = tick.modules[primary.module_id]
  const medical = primary.kind === 'medical' && primary.subject
  const open = () => (primary.subject ? ui.openCrew(primary.subject) : ui.setSheetEmergency(primary.id))
  const tres = primary.kind === 'depressurization' && primary.tres_s != null

  return (
    <Frame level={level} pulse={critical}>
      <div className="flex items-start gap-6">
        <div className="min-w-0 flex-1">
          <Label level={level} text={critical ? 'Intervento richiesto · Critico' : suspected ? 'Segnale in verifica' : 'Attenzione'} />
          <h1 className={cn('mt-2 font-light leading-[1.02] tracking-[-.025em]', critical ? 'text-[46px]' : 'text-[34px]')} role="alert" aria-live="assertive">{title}</h1>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {primary.subject ? <CrewChip id={primary.subject} /> : <ModuleChip id={primary.module_id} />}
            {!medical && mod?.occupants.map((o) => <CrewChip key={o} id={o} />)}
          </div>
          <div className="mt-3 flex gap-10">
            {nums.map((n) => (
              <div key={n.label}>
                <div className="lbl">{n.label}</div>
                <div className="num text-[30px]">{n.value}<span className="ml-1 text-sm text-muted-foreground">{n.unit}</span></div>
              </div>
            ))}
            {tres && <div><div className="lbl">Conto alla rovescia</div><div className="num text-[30px] text-crit">{fmtClock(primary.tres_s as number)}</div></div>}
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button variant={critical ? 'danger' : 'outline'} onClick={open}>Apri risposta →</Button>
            <Button variant="outline" onClick={() => ui.showToast('Contatto con la Terra non collegato')}>Contatta la Terra</Button>
            {pending > 0 && <button type="button" onClick={ui.reopenPending} className="rounded-full border border-warn/50 bg-warn/10 px-3 py-1 text-xs text-warn">{pending} {pending === 1 ? 'azione' : 'azioni'} in attesa di conferma</button>}
          </div>
          {others.length > 0 && <p className="mt-3 text-xs text-muted-foreground">Anche: {others.map((e: Emergency) => emergencyTitle(e)).join(' · ')}</p>}
        </div>
        {medical && <MiniHolo tick={tick} id={primary.subject as string} />}
      </div>
    </Frame>
  )
}

const lowerFirst = (s: string, lower: boolean) => (lower ? s.charAt(0).toLowerCase() + s.slice(1) : s)

function Label({ level, text }: { level: Status; text: string }) {
  return <div className="lbl flex items-center gap-2" style={{ color: statusColor[level] }}><span className={cn('size-2 rounded-full', level === 'crit' && 'anim-ping')} style={{ background: statusColor[level] }} />{text}</div>
}

function Frame({ level, pulse, children }: { level: Status; pulse: boolean; children: React.ReactNode }) {
  return (
    <div
      className={cn('relative rounded-3xl border-[1.5px] px-7 py-5', pulse && 'anim-glow', level === 'crit' ? 'border-crit/75' : 'border-warn/60')}
      style={{ background: level === 'crit' ? 'linear-gradient(95deg, hsl(4 100% 62% / .22), hsl(4 100% 62% / .07) 55%, transparent)' : 'linear-gradient(95deg, hsl(38 100% 58% / .14), hsl(38 100% 58% / .04) 55%, transparent)' }}
    >
      <CornerBrackets color={level === 'crit' ? 'hsl(4 100% 62% / .8)' : 'hsl(38 100% 58% / .7)'} />
      {children}
    </div>
  )
}
