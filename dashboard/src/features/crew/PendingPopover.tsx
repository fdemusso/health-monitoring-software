import { X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useUi } from '@/app/ui-context'
import { emergencyTitle } from '@/domain/emergencyText'
import { usePendingActions, useTick } from '@/telemetry/useTelemetry'
import { PendingActionCard } from './PendingActionCard'

/** Floating card that appears on any page when the monitor proposes a step to confirm. */
export function PendingPopover() {
  const tick = useTick()
  const pending = usePendingActions()
  const { pendingReopen } = useUi()
  const [hidden, setHidden] = useState<Set<string>>(new Set())

  // The banner badge asks to show the popover again.
  useEffect(() => { if (pendingReopen) setHidden(new Set()) }, [pendingReopen])

  const visible = pending.filter((p) => !hidden.has(p.action.id))
  if (!tick || visible.length === 0) return null
  const hide = () => setHidden(new Set([...hidden, ...visible.map((p) => p.action.id)]))

  return (
    <div className="pointer-events-none fixed inset-x-0 top-20 z-40 flex justify-center px-4">
      <div role="alertdialog" aria-label="Azione da confermare" className="pointer-events-auto w-[520px] max-w-full rounded-3xl border border-warn/60 bg-card p-5 shadow-[0_20px_60px_rgb(0_0_0/.6),0_0_40px_hsl(38_100%_58%/.15)] animate-in fade-in zoom-in-95 slide-in-from-top-4 duration-200">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <div className="lbl text-warn">Azione da confermare</div>
            <div className="mt-0.5 text-lg font-light">
              {emergencyTitleFor(tick.emergencies, visible[0].action.emergency_id)}
            </div>
          </div>
          <button type="button" aria-label="Nascondi" onClick={hide} className="grid size-11 shrink-0 place-items-center rounded-full border border-white/15"><X size={18} /></button>
        </div>
        <div className="max-h-[50vh] space-y-3 overflow-y-auto">
          {visible.map((p) => <PendingActionCard key={p.action.id} pa={p} tSim={tick.t_sim_s} />)}
        </div>
      </div>
    </div>
  )
}

function emergencyTitleFor(list: import('@/telemetry').Emergency[], id: string) {
  const e = list.find((x) => x.id === id)
  return e ? emergencyTitle(e) : 'Emergenza'
}
