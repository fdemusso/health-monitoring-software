import { useUi } from '@/app/ui-context'
import { useCrewList, useEmergencies } from '@/telemetry/useTelemetry'
import { CrewPill } from './CrewPill'
import { LinkStatus } from './LinkStatus'

export function CrewStrip() {
  const crew = useCrewList()
  const emergencies = useEmergencies()
  const { openCrew } = useUi()
  return (
    <header className="relative z-[2] flex items-center gap-2.5 px-7 pt-4">
      {crew.length === 0
        ? Array.from({ length: 4 }, (_, i) => <div key={i} className="h-[46px] w-44 rounded-full bg-white/[.04]" />)
        : crew.map((n) => <CrewPill key={n.id} npc={n} emergencies={emergencies} onOpen={() => openCrew(n.id)} />)}
      <div className="flex-1" />
      <LinkStatus />
    </header>
  )
}
