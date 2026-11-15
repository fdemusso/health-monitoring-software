import { useState } from 'react'
import { useTick } from '@/telemetry/useTelemetry'
import { AlertBanner } from './AlertBanner'
import { AlertList } from './AlertList'
import { EnvironmentHead, EnvironmentTiles } from './EnvironmentPanel'
import { VitalsChart } from './VitalsChart'

export function StatusPage() {
  const tick = useTick()
  const [chosen, setChosen] = useState<string | null>(null)
  return (
    <div className="grid min-h-full grid-cols-[350px_1fr] content-start gap-y-4 px-7 pb-12 pt-[18px]">
      {!tick ? (
        <div className="col-span-full space-y-4">
          <div className="h-[90px] rounded-3xl bg-white/[.04]" />
          <div className="h-32 rounded-3xl bg-white/[.04]" />
        </div>
      ) : (
        <>
          <div className="col-span-full space-y-4">
            <AlertBanner tick={tick} />
            <EnvironmentHead tick={tick} chosen={chosen} onChoose={setChosen} />
          </div>
          <div className="col-start-2 space-y-5">
            <EnvironmentTiles tick={tick} chosen={chosen} />
            <div className="grid grid-cols-[1.6fr_1fr] gap-8">
              <VitalsChart />
              <AlertList tick={tick} />
            </div>
          </div>
        </>
      )}
    </div>
  )
}
