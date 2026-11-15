import { useUi } from '@/app/ui-context'
import { useCrewList, useTick } from '@/telemetry/useTelemetry'
import { CrewColumn } from './CrewColumn'
import { CrewDetail } from './CrewDetail'

export function CrewPage() {
  const tick = useTick()
  const crew = useCrewList()
  const ui = useUi()
  if (!tick) return <div className="px-7 pt-[18px]"><div className="h-64 rounded-3xl bg-white/[.04]" /></div>
  const npc = ui.selectedCrew ? tick.npcs[ui.selectedCrew] : undefined
  return (
    <div className="grid min-h-full grid-cols-[350px_1fr] grid-rows-[auto_1fr] gap-y-4 px-7 pb-12 pt-[18px]">
      {npc ? <CrewDetail npc={npc} tick={tick} onBack={ui.closeCrew} /> : (
        <>
          <div className="col-span-full">
            <div className="lbl">Equipaggio</div>
            <h1 className="mt-1 text-[30px] font-light tracking-tight">Tocca un astronauta per il dettaglio completo</h1>
          </div>
          <div className="col-start-2 grid grid-cols-4 gap-3 animate-in fade-in duration-150" style={{ minHeight: 420 }}>
            {crew.map((n) => <CrewColumn key={n.id} npc={n} tick={tick} onOpen={() => ui.openCrew(n.id)} />)}
          </div>
        </>
      )}
    </div>
  )
}
