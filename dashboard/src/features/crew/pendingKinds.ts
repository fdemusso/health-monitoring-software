import { Cog, DoorOpen, Fan, FireExtinguisher, Gauge, Megaphone, Zap, type LucideIcon } from 'lucide-react'

/** Label and icon of each kind of action the monitor can propose (`Action.kind`). */
export const PENDING_KIND: Record<string, { label: string; Icon: LucideIcon }> = {
  extinguish: { label: 'Fire extinguisher', Icon: FireExtinguisher },
  actuator: { label: 'Equipment', Icon: Cog },
  hatch: { label: 'Door (hatch)', Icon: DoorOpen },
  announce: { label: 'Announcement', Icon: Megaphone },
  ventilation: { label: 'Ventilation', Icon: Fan },
  power: { label: 'Module power', Icon: Zap },
  sensor: { label: 'Sensor', Icon: Gauge },
}
