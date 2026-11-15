import { useEffect, type ReactNode } from 'react'
import { DebugPanel } from '@/features/debug/DebugPanel'
import { HoneycombNav } from '@/features/nav/HoneycombNav'
import { CrewStrip } from '@/features/shell/CrewStrip'
import { StatusPage } from '@/features/status/StatusPage'
import { CrewPage } from '@/features/crew/CrewPage'
import { EventLogSheet } from '@/features/log/EventLogSheet'
import { EmergencySheet } from '@/features/log/EmergencySheet'
import { globalStatus } from '@/domain/status'
import { startTelemetry } from '@/telemetry/createBackend'
import { useCrewList, useEmergencies } from '@/telemetry/useTelemetry'
import { ConnectionBanner } from './ConnectionBanner'
import { PageSwiper } from './PageSwiper'
import { Pager } from './Pager'
import { UiProvider, useUi } from './ui-context'

function Vignette() {
  const crew = useCrewList()
  const emergencies = useEmergencies()
  if (globalStatus(crew, emergencies) !== 'crit') return null
  return <div aria-hidden className="anim-breathe pointer-events-none fixed inset-0 z-[1]" />
}

function Toast(): ReactNode {
  const { toast } = useUi()
  return toast ? <div role="status" className="fixed bottom-24 left-1/2 z-40 -translate-x-1/2 rounded-full border bg-card px-5 py-2 text-sm">{toast}</div> : null
}

function Shell() {
  useEffect(() => { startTelemetry() }, [])
  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <ConnectionBanner />
      <CrewStrip />
      <PageSwiper pages={[<StatusPage key="s" />, <CrewPage key="c" />]} />
      <Vignette />
      <HoneycombNav />
      <Pager />
      <DebugPanel />
      <EventLogSheet />
      <EmergencySheet />
      <Toast />
    </div>
  )
}

export default function App() {
  return <UiProvider><Shell /></UiProvider>
}
