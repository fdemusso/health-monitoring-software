import { useState } from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import { useTick } from '@/telemetry/useTelemetry'
import { AlertBanner } from './AlertBanner'
import { AlertList } from './AlertList'
import { CrewActivity } from './CrewActivity'
import { EnvironmentHead, EnvironmentTiles } from './EnvironmentPanel'
import { VitalsChart } from './VitalsChart'

/** One screen when it fits: banner, module + tiles on top, the vitals chart and the lists fill what is left. On a short screen (iPad) the lists keep a readable minimum and the page scrolls. */
export function StatusPage() {
  const tick = useTick()
  const [chosen, setChosen] = useState<string | null>(null)
  return (
    <div className="flex min-h-full flex-col gap-3 px-7 pb-16 pt-[18px]">
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
          <div className="grid min-h-[24rem] flex-1 grid-cols-[2fr_1fr] gap-8">
            <div className="min-h-0 min-w-0"><VitalsChart /></div>
            <div className="flex min-h-0 flex-col gap-4"><AlertList tick={tick} /><CrewActivity tick={tick} /></div>
          </div>
        </>
      )}
    </div>
  )
}
