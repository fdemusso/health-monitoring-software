import { ChevronLeft, ChevronRight, Cog, DoorOpen, Fan, FireExtinguisher, Megaphone, X, type LucideIcon } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useUi } from '@/app/ui-context'
import { CrewChip, ModuleChip } from '@/components/CrewChip'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { emergencyTitle } from '@/domain/emergencyText'
import { fmtClock } from '@/domain/units'
import { cn } from '@/lib/utils'
import { DragHandles, useDraggable } from '@/lib/useDraggable'
import type { Emergency, PendingAction } from '@/telemetry'
import { useCommands, usePendingActions, useTick } from '@/telemetry/useTelemetry'

const KIND: Record<string, { label: string; Icon: LucideIcon }> = {
  extinguish: { label: 'Extinguisher', Icon: FireExtinguisher },
  actuator: { label: 'Actuator', Icon: Cog },
  hatch: { label: 'Hatch', Icon: DoorOpen },
  announce: { label: 'Announcement', Icon: Megaphone },
  ventilation: { label: 'Ventilation', Icon: Fan },
}

/** Centered confirmation for a step the monitor proposes: one action at a time, countdown first. */
export function PendingPopover() {
  const tick = useTick()
  const pending = usePendingActions()
  const { pendingReopen } = useUi()
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const [index, setIndex] = useState(0)
  const { ref, offset, dragging, handleProps } = useDraggable<HTMLDivElement>()

  // The banner badge asks to show the popover again.
  useEffect(() => { if (pendingReopen) setHidden(new Set()) }, [pendingReopen])

  const visible = pending.filter((p) => !hidden.has(p.action.id))
  if (!tick || visible.length === 0) return null
  const i = Math.min(index, visible.length - 1)
  const hide = () => setHidden(new Set([...hidden, ...visible.map((p) => p.action.id)]))
  const emergency = tick.emergencies.find((e) => e.id === visible[i].action.emergency_id)

  return (
    <div className="pointer-events-none fixed inset-0 z-40 flex items-center justify-center p-4">
      {/* the wrapper is moved (relative offset) and carries the handles; the card inside keeps its rounded, clipped look */}
      <div ref={ref} className="pointer-events-auto relative w-[760px] max-w-full" style={{ left: offset.x, top: offset.y }}>
      <DragHandles handleProps={handleProps} dragging={dragging} />
      <div role="alertdialog" aria-label="Action to confirm" className="overflow-hidden rounded-lg border border-border bg-card animate-in fade-in-0 zoom-in-95 slide-in-from-bottom-6 duration-(--duration-enter)">
        <div className="h-1 bg-status-warning" />
        <div className="p-7">
          <div className="mb-6 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm font-medium text-status-warning-foreground">
              <span className="anim-ping size-2 rounded-full bg-status-warning" aria-hidden />
              Action to confirm
            </div>
            <div className="flex items-center gap-1">
              {visible.length > 1 && (
                <>
                  <Button variant="ghost" size="icon" aria-label="Previous action" disabled={i === 0} onClick={() => setIndex(i - 1)}><ChevronLeft /></Button>
                  <span className="text-sm tabular-nums text-muted-foreground">{i + 1} of {visible.length}</span>
                  <Button variant="ghost" size="icon" aria-label="Next action" disabled={i === visible.length - 1} onClick={() => setIndex(i + 1)}><ChevronRight /></Button>
                </>
              )}
              <Button variant="ghost" size="icon" aria-label="Hide" onClick={hide}><X /></Button>
            </div>
          </div>
          <ActionView key={visible[i].action.id} pa={visible[i]} tSim={tick.t_sim_s} emergency={emergency} />
        </div>
      </div>
      </div>
    </div>
  )
}

function ActionView({ pa, tSim, emergency }: { pa: PendingAction; tSim: number; emergency?: Emergency }) {
  const cmd = useCommands()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const a = pa.action
  const { label, Icon } = KIND[a.kind] ?? { label: a.kind, Icon: Cog }
  const left = Math.max(0, pa.deadline_s - tSim)
  const total = Math.max(1, pa.deadline_s - pa.t_proposed_s)
  const tone = left <= 10 ? 'danger' : left <= 30 ? 'warning' : 'neutral'
  const execute = pa.on_timeout === 'execute'

  const run = async (fn: () => ReturnType<typeof cmd.approve>) => {
    setBusy(true); setError(null)
    const r = await fn()
    if (!r.ok) { setError(r.error ?? 'rejected'); setBusy(false) }
    // On success the view disappears when the next tick no longer lists it.
  }

  return (
    <div className="grid grid-cols-[1fr_auto] items-start gap-x-8 gap-y-5">
      <div className="min-w-0">
        <div className="mb-3 flex items-center gap-3">
          <span className="grid size-11 shrink-0 place-items-center rounded-control bg-status-warning-soft text-status-warning-foreground"><Icon className="size-6" /></span>
          <div className="min-w-0">
            <div className="text-sm text-muted-foreground">{emergency ? emergencyTitle(emergency) : 'Emergency'}</div>
            <h2 className="font-heading text-4xl font-bold">{label}</h2>
          </div>
        </div>
        <p className="text-base">{a.reason || `${a.command} ${a.target}`}</p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {emergency?.subject ? <CrewChip id={emergency.subject} /> : emergency ? <ModuleChip id={emergency.module_id} /> : null}
          <Badge variant="outline">{a.command} {a.target}</Badge>
          {a.reversible && <Badge>Reversible</Badge>}
        </div>
      </div>

      <div className="min-w-44 text-right">
        <div className="text-sm text-muted-foreground">Time left</div>
        <div className={cn('num text-5xl', tone === 'danger' && 'text-status-danger-foreground', tone === 'warning' && 'text-status-warning-foreground')}>{fmtClock(left)}</div>
      </div>

      <div className="col-span-2">
        <Progress value={(left / total) * 100} indicatorClassName={tone === 'danger' ? 'bg-status-danger' : tone === 'warning' ? 'bg-status-warning' : 'bg-muted-foreground'} />
        <p className="mt-2 text-sm text-muted-foreground">
          {execute ? 'If no one responds, the action will be executed.' : 'If no one responds, the action will be discarded.'}
        </p>
      </div>

      <div className="col-span-2 flex items-center gap-3">
        <Button variant="outline" className="h-12 flex-1 text-base hover:border-status-live hover:bg-status-live-soft hover:text-status-live-foreground active:border-status-live active:bg-status-live-soft active:text-status-live-foreground" disabled={busy} onClick={() => run(() => cmd.approve(a.id))}>Approve</Button>
        <Button variant="outline" className="h-12 flex-1 text-base hover:border-status-danger hover:bg-status-danger-soft hover:text-status-danger-foreground active:border-status-danger active:bg-status-danger-soft active:text-status-danger-foreground" disabled={busy} onClick={() => run(() => cmd.reject(a.id))}>Reject</Button>
      </div>
      {error && <p className="col-span-2 text-sm text-status-danger-foreground">{error}</p>}
    </div>
  )
}
