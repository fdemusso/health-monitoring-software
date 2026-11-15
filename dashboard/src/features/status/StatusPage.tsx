import { useState } from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import { useTick } from '@/telemetry/useTelemetry'
import { AlertBanner } from './AlertBanner'
import { AlertList } from './AlertList'
import { CrewActivity } from './CrewActivity'
import { EnvironmentHead, EnvironmentTiles } from './EnvironmentPanel'
import { VitalsChart } from './VitalsChart'

/** One screen, no scrolling: banner, module + tiles on top, the vitals chart fills what is left. */
export function StatusPage() {
  const tick = useTick()
  const [chosen, setChosen] = useState<string | null>(null)
  return (
    <div className="flex h-full min-h-[35rem] flex-col gap-3 px-7 pb-16 pt-[18px]">
      {!tick ? (
        <div className="space-y-4">
          <Skeleton className="h-[90px]" />
          <Skeleton className="h-32" />
        </div>
      ) : (
        <>
          <AlertBanner tick={tick} />
          <EnvironmentHead tick={tick} chosen={chosen} onChoose={setChosen} />
          <EnvironmentTiles tick={tick} chosen={chosen} />
          <div className="grid min-h-0 flex-1 grid-cols-[2fr_1fr] gap-8">
            <div className="min-h-0 min-w-0"><VitalsChart /></div>
            <div className="min-h-0 space-y-5 overflow-y-auto"><AlertList tick={tick} /><CrewActivity tick={tick} /></div>
          </div>
        </>
      )}
    </div>
  )
}
