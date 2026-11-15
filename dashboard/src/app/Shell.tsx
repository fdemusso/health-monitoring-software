import { useEffect } from 'react'
import { CrewPage } from '@/features/crew/CrewPage'
import { EmergencyDialog } from '@/features/crew/EmergencyDialog'
import { PendingPopover } from '@/features/crew/PendingPopover'
import { ProtocolsDialog } from '@/features/crew/ProtocolsDialog'
import { DebugPanel } from '@/features/debug/DebugPanel'
import { EventLogSheet } from '@/features/log/EventLogSheet'
import { ModulesDialog } from '@/features/modules/ModulesDialog'
import { AlertsDialog } from '@/features/status/AlertsDialog'
import { StatusPage } from '@/features/status/StatusPage'
import { startTelemetry } from '@/telemetry/createBackend'
import { useWaiting, useWarmup } from '@/telemetry/useTelemetry'
import { Toast, Vignette } from './feedback'
import { HoneycombNav } from './nav/HoneycombNav'
import { ConnectionBanner } from './shell/ConnectionBanner'
import { CrewStrip } from './shell/CrewStrip'
import { PageSwiper, type SwiperPage } from './shell/PageSwiper'
import { Pager } from './shell/Pager'

/** The two swipeable pages, in order. The index is `useUi().page`. */
const PAGES: SwiperPage[] = [
  { id: 'status', label: 'Status', node: <StatusPage /> },
  { id: 'crew', label: 'Crew', node: <CrewPage /> },
]

/** Landmarks: header (CrewStrip), main (the pages), nav (corner menu). Everything else is a dialog or an overlay. */
export function Shell() {
  useEffect(() => { startTelemetry() }, [])
  // While the backend warms up the WarmupScreen covers everything: keep focus and screen readers out of what is behind it.
  const warming = useWarmup()
  const waiting = useWaiting()
  return (
    <div inert={waiting || (warming !== null && !warming.finishing)} className="flex h-dvh flex-col overflow-hidden portrait:hidden">
      <a href="#main" className="sr-only z-[200] rounded-control bg-card px-4 py-2 text-sm font-medium focus:not-sr-only focus:fixed focus:left-4 focus:top-4">Skip to main content</a>
      <ConnectionBanner />
      <CrewStrip />
      <PageSwiper pages={PAGES} />
      <Vignette />
      <HoneycombNav />
      <Pager labels={PAGES.map((p) => p.label)} />
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
