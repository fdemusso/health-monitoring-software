import { Skeleton } from '@/components/ui/skeleton'
import { useUi } from '@/app/ui-context'
import { useCrewList, useEmergencies } from '@/telemetry/useTelemetry'
import { CrewPill } from './CrewPill'
import { LinkStatus } from './LinkStatus'

export function CrewStrip() {
  const crew = useCrewList()
  const emergencies = useEmergencies()
  const { openCrew, closeCrew, selectedCrew } = useUi()
  return (
    <header className="relative z-[2] flex items-center gap-2 px-5 pt-4 min-[1200px]:gap-2.5 min-[1200px]:px-7">
      {crew.length === 0
        ? Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-[46px] w-44 rounded-full" />)
        : crew.map((n) => <CrewPill key={n.id} npc={n} emergencies={emergencies} selected={selectedCrew === n.id} onOpen={() => (selectedCrew === n.id ? closeCrew() : openCrew(n.id))} />)}
      <div className="min-w-2 flex-1" />
      <LinkStatus />
    </header>
  )
}
