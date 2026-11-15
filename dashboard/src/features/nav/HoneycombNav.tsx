import { Activity, Bell, ClipboardList, History, LayoutGrid, Users } from 'lucide-react'
import type { ComponentType } from 'react'
import { useUi } from '@/app/ui-context'
import { CREW_ORDER } from '@/domain/crewConfig'
import { crewStatus, primaryEmergency, isCriticalConfirmed, RANKED } from '@/domain/status'
import { cn } from '@/lib/utils'
import { useCrewList, useEmergencies } from '@/telemetry/useTelemetry'
import { CELLS, CLIP, HEX_H, HEX_W, cellPosition, type CellId } from './hexGeometry'

const ICON: Record<CellId, ComponentType<{ size?: number; strokeWidth?: number }>> = {
  alerts: Bell, protocols: ClipboardList, history: History, status: Activity, crew: Users, env: LayoutGrid,
}

export function HoneycombNav() {
  const ui = useUi()
  const emergencies = useEmergencies()
  const crew = useCrewList()
  const { primary } = primaryEmergency(emergencies)

  const urgentCrew = () => {
    if (primary?.subject) return primary.subject
    const worst = [...crew].sort((a, b) => RANKED(crewStatus(b, emergencies)) - RANKED(crewStatus(a, emergencies)))[0]
    return worst?.id ?? CREW_ORDER[0]
  }

  const act = (id: CellId) => {
    switch (id) {
      case 'status': case 'alerts': ui.setPage(0); break
      case 'crew': ui.closeCrew(); ui.setPage(1); break
      case 'protocols': ui.openCrew(urgentCrew()); break
      case 'history': ui.setLogOpen(true); break
      case 'env': ui.showToast('Ambiente: in arrivo'); break
    }
  }
  const active = (id: CellId) => (id === 'status' || id === 'alerts' ? ui.page === 0 && id === 'status' : id === 'crew' ? ui.page === 1 && !ui.selectedCrew : id === 'protocols' ? ui.page === 1 && !!ui.selectedCrew : false)

  return (
    <nav aria-label="Navigazione" className="pointer-events-none fixed bottom-0 left-0 z-20 h-[370px] w-[360px]" style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}>
      {CELLS.map((c) => {
        const Icon = ICON[c.id]
        const on = active(c.id)
        const pos = cellPosition(c.R, c.deg)
        const alertDot = c.id === 'alerts' && isCriticalConfirmed(primary)
        return (
          <button
            key={c.id}
            type="button"
            aria-label={c.label}
            onClick={() => act(c.id)}
            className="pointer-events-auto absolute transition active:scale-[.94]"
            style={{ width: HEX_W, height: HEX_H, left: pos.left, bottom: pos.bottom, clipPath: CLIP, background: 'rgb(255 255 255 / .2)' }}
          >
            <span
              className={cn('absolute inset-[1.5px] flex flex-col items-center justify-center gap-1.5', on ? 'bg-[#f2f4f7] text-[#05070a]' : 'bg-[hsl(220_20%_6%)] text-foreground')}
              style={{ clipPath: CLIP }}
            >
              <Icon size={32} strokeWidth={1.5} />
              <span className="text-[11px] font-medium uppercase tracking-wider">{c.label}</span>
            </span>
            {alertDot && <span className="anim-ping absolute right-[30px] top-[24px] size-2.5 rounded-full bg-crit" />}
          </button>
        )
      })}
    </nav>
  )
}
