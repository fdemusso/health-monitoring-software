import { Skeleton } from '@/components/ui/skeleton'
import { useUi } from '@/app/ui-context'
import { useCrewList, useTick } from '@/telemetry/useTelemetry'
import { CrewColumn } from './CrewColumn'
import { CrewDetail } from './CrewDetail'

export function CrewPage() {
  const tick = useTick()
  const crew = useCrewList()
  const ui = useUi()
  if (!tick) return <div className="px-7 pt-[18px]"><Skeleton className="h-64" /></div>
  const npc = ui.selectedCrew ? tick.npcs[ui.selectedCrew] : undefined
  return (
    <div className="grid min-h-full grid-cols-1 grid-rows-[auto_1fr] gap-y-4 px-7 pb-28 pt-[18px]">
      {npc ? <CrewDetail npc={npc} tick={tick} onBack={ui.closeCrew} /> : (
        <>
          <div className="col-span-full">
            <div className="lbl">Crew</div>
            <h1 className="mt-1 font-heading text-4xl font-bold">Tap an astronaut for full details</h1>
          </div>
          <div className="grid grid-cols-4 gap-3 animate-in fade-in-0 duration-(--duration-enter)" style={{ minHeight: 420 }}>
            {crew.map((n) => <CrewColumn key={n.id} npc={n} tick={tick} onOpen={() => ui.openCrew(n.id)} />)}
          </div>
        </>
      )}
    </div>
  )
}
