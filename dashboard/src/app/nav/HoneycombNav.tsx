import { Activity, Bell, ClipboardList, History, Menu, Users, X } from 'lucide-react'
import { useEffect, useState, type ComponentType } from 'react'
import { useUi } from '@/app/ui-context'
import { isCriticalConfirmed, primaryEmergency } from '@/domain/status'
import { cn } from '@/lib/utils'
import { alertRows } from '@/features/status/alertRows'
import { useEmergencies, usePendingActions, useTick } from '@/telemetry/useTelemetry'
import { useUiScale } from '@/lib/useUiScale'
import { CELL as CELL0, CELLS, CLIP, TRIGGER as TRIGGER0, cellOffset, type CellId } from './hexGeometry'

const ICON: Record<CellId, ComponentType<{ size?: number; strokeWidth?: number }>> = {
  status: Activity, crew: Users, alerts: Bell, protocols: ClipboardList, history: History,
}

function Hex({ w, h, on, children, className }: { w: number; h: number; on?: boolean; children: React.ReactNode; className?: string }) {
  return (
    <span className={cn('absolute inset-0 block', className)} style={{ width: w, height: h, clipPath: CLIP, background: 'var(--input)' }}>
      <span className={cn('absolute inset-[1.5px] flex flex-col items-center justify-center gap-1.5', on ? 'bg-sidebar-active text-sidebar-active-foreground' : 'bg-card text-foreground')} style={{ clipPath: CLIP }}>
        {children}
      </span>
    </span>
  )
}

/** Corner menu: one hexagon when closed (with emergency indicators); the cells fan out on an arc when open. */
export function HoneycombNav() {
  const ui = useUi()
  const sc = useUiScale()
  // the geometry is drawn at 16 px per rem: scale it like the rest of the UI
  const TRIGGER = { w: TRIGGER0.w * sc, h: TRIGGER0.h * sc, cx: TRIGGER0.cx * sc, cy: TRIGGER0.cy * sc }
  const CELL = { w: CELL0.w * sc, h: CELL0.h * sc }
  const [open, setOpen] = useState(false)
  const emergencies = useEmergencies()
  const pending = usePendingActions()
  const tick = useTick()
  // No active alarms: the Alarms cell is dimmed, like a switched-off light.
  const noAlerts = !!tick && alertRows(tick).length === 0
  // Protocols are for an emergency: with none open the cell is dimmed too (the protocol appears by itself when one opens).
  const noEmergency = !!tick && !emergencies.some((e) => e.state !== 'cleared')
  const off = (id: CellId) => (id === 'alerts' && noAlerts) || (id === 'protocols' && noEmergency)
  const { primary } = primaryEmergency(emergencies)
  const critical = isCriticalConfirmed(primary)

  useEffect(() => {
    if (!open) return
    const h = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [open])

  const act = (id: CellId) => {
    setOpen(false)
    switch (id) {
      case 'status': ui.setPage(0); break
      case 'alerts': ui.setAlertsOpen(true); break
      case 'crew': ui.closeCrew(); ui.setPage(1); break
      case 'protocols': ui.setProtocolsOpen(true); break
      case 'history': ui.setLogOpen(true); break
    }
  }
  const active = (id: CellId) =>
    id === 'status' ? ui.page === 0 : id === 'crew' ? ui.page === 1 : false
  const CurrentIcon = ICON[ui.page === 0 ? 'status' : 'crew']

  const label = `Menu${critical ? ', critical emergency' : ''}${pending.length ? `, ${pending.length} pending ${pending.length === 1 ? 'action' : 'actions'}` : ''}`

  return (
    <nav aria-label="Navigation" className="pointer-events-none fixed inset-0 z-20" style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}>
      {/* scrim: dims the page while the menu is open; tap outside closes */}
      <div
        aria-hidden
        onClick={() => setOpen(false)}
        className={cn('absolute inset-0 bg-scrim transition-opacity', open ? 'pointer-events-auto opacity-100 duration-(--duration-enter)' : 'opacity-0 duration-(--duration-exit)')}
      />

      {CELLS.map((c, k) => {
        const Icon = ICON[c.id]
        const o0 = cellOffset(k)
        const o = { x: o0.x * sc, y: o0.y * sc }
        const disabled = off(c.id)
        return (
          <button
            key={c.id}
            type="button"
            aria-label={c.label}
            disabled={disabled}
            inert={!open}
            onClick={() => act(c.id)}
            className={cn('absolute transition-[transform,opacity] duration-(--duration-enter) ease-out active:scale-[.94]', open && !disabled ? 'pointer-events-auto opacity-100' : open ? 'pointer-events-none opacity-100' : 'pointer-events-none opacity-0')}
            style={{
              width: CELL.w, height: CELL.h,
              left: TRIGGER.cx + o.x - CELL.w / 2, bottom: TRIGGER.cy + o.y - CELL.h / 2,
              transform: open ? 'none' : `translate(${-o.x}px, ${o.y}px) scale(.5)`,
              transitionDelay: open ? `${k * 25}ms` : '0ms',
            }}
          >
            <Hex w={CELL.w} h={CELL.h} on={active(c.id)} className={disabled ? 'opacity-35' : undefined}>
              <Icon size={28 * sc} strokeWidth={1.5} />
              <span className="text-xs font-medium">{c.label}</span>
            </Hex>
            {c.id === 'alerts' && critical && <span className="anim-ping absolute right-[22px] top-[18px] size-2.5 rounded-full bg-status-danger" />}
          </button>
        )
      })}

      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="pointer-events-auto absolute transition active:scale-[.94]"
        style={{ width: TRIGGER.w, height: TRIGGER.h, left: TRIGGER.cx - TRIGGER.w / 2, bottom: TRIGGER.cy - TRIGGER.h / 2 }}
      >
        <Hex w={TRIGGER.w} h={TRIGGER.h}>{open ? <X size={26 * sc} strokeWidth={1.5} /> : <CurrentIcon size={26 * sc} strokeWidth={1.5} />}</Hex>
        {!open && <Menu aria-hidden size={12} className="absolute bottom-[22px] left-1/2 -translate-x-1/2 text-muted-foreground" />}
        {!open && critical && <span className="anim-ping absolute right-[16px] top-[14px] size-3 rounded-full bg-status-danger" />}
        {!open && !critical && primary && <span className="absolute right-[16px] top-[14px] size-3 rounded-full bg-status-warning" />}
        {!open && pending.length > 0 && (
          <span className="absolute right-[6px] top-[38px] grid h-5 min-w-5 place-items-center rounded-full bg-signal px-1 text-xs font-medium text-signal-on">{pending.length}</span>
        )}
      </button>
    </nav>
  )
}
