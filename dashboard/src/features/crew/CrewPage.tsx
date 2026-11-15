import { Skeleton } from '@/components/ui/skeleton'
import { useUi } from '@/app/ui-context'
import { useCrewList, useTick } from '@/telemetry/useTelemetry'
import { CrewColumn } from './CrewColumn'

/** The four astronauts side by side; a tap opens the detail popover (CrewDetailDialog). */
export function CrewPage() {
  const tick = useTick()
  const crew = useCrewList()
  const ui = useUi()
  if (!tick) return <div className="px-7 pt-[18px]"><Skeleton className="h-64" /></div>
  return (
    <div className="grid min-h-full grid-cols-1 grid-rows-[auto_1fr] gap-y-4 px-7 pb-28 pt-[18px]">
      <div className="col-span-full">
        <div className="lbl">Crew</div>
        <h2 className="mt-1 font-heading text-4xl font-bold">Tap an astronaut for full details</h2>
      </div>
      <ul className="grid min-h-[420px] grid-cols-4 gap-3 animate-in fade-in-0 duration-(--duration-enter)">
        {crew.map((n) => <li key={n.id} className="contents"><CrewColumn npc={n} tick={tick} onOpen={() => ui.openCrew(n.id)} /></li>)}
      </ul>
    </div>
  )
}
