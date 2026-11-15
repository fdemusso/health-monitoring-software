import { useEffect, type ReactNode } from 'react'
import { DebugPanel } from '@/features/debug/DebugPanel'
import { HoneycombNav } from '@/features/nav/HoneycombNav'
import { CrewStrip } from '@/features/shell/CrewStrip'
import { StatusPage } from '@/features/status/StatusPage'
import { CrewPage } from '@/features/crew/CrewPage'
import { PendingPopover } from '@/features/crew/PendingPopover'
import { EventLogSheet } from '@/features/log/EventLogSheet'
import { AlertsDialog } from '@/features/status/AlertsDialog'
import { ProtocolsDialog } from '@/features/crew/ProtocolsDialog'
import { ModulesDialog } from '@/features/modules/ModulesDialog'
import { EmergencyDialog } from '@/features/log/EmergencyDialog'
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
  return toast ? <div role="status" className="fixed bottom-24 left-1/2 z-40 -translate-x-1/2 rounded-full border border-border bg-card px-5 py-2 text-sm font-medium animate-in fade-in-0 duration-(--duration-enter)">{toast}</div> : null
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
      <EmergencyDialog />
      <AlertsDialog />
      <ProtocolsDialog />
      <ModulesDialog />
      <PendingPopover />
      <Toast />
    </div>
  )
}

export default function App() {
  return <UiProvider><Shell /></UiProvider>
}
