import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'

interface UiState {
  page: 0 | 1
  setPage: (p: 0 | 1) => void
  selectedCrew: string | null
  /** Opens the crew page with the astronaut's detail. */
  openCrew: (id: string) => void
  closeCrew: () => void
  logOpen: boolean
  setLogOpen: (v: boolean) => void
  alertsOpen: boolean
  setAlertsOpen: (v: boolean) => void
  protocolsOpen: boolean
  setProtocolsOpen: (v: boolean) => void
  modulesOpen: boolean
  setModulesOpen: (v: boolean) => void
  /** Emergency id whose response sheet is open. */
  sheetEmergency: string | null
  setSheetEmergency: (id: string | null) => void
  toast: string | null
  /** Counter: bumping it shows the pending-action popover again. */
  pendingReopen: number
  reopenPending: () => void
  showToast: (m: string) => void
}

const Ctx = createContext<UiState | null>(null)

export function UiProvider({ children }: { children: ReactNode }) {
  const [page, setPage] = useState<0 | 1>(0)
  const [selectedCrew, setSelected] = useState<string | null>(null)
  const [logOpen, setLogOpen] = useState(false)
  const [alertsOpen, setAlertsOpen] = useState(false)
  const [protocolsOpen, setProtocolsOpen] = useState(false)
  const [modulesOpen, setModulesOpen] = useState(() => new URLSearchParams(window.location.search).get('open') === 'modules')
  const [sheetEmergency, setSheetEmergency] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [pendingReopen, setPendingReopen] = useState(0)
  const value = useMemo<UiState>(() => ({
    page, setPage, selectedCrew, logOpen, setLogOpen, alertsOpen, setAlertsOpen, protocolsOpen, setProtocolsOpen, modulesOpen, setModulesOpen, sheetEmergency, setSheetEmergency, toast, pendingReopen,
    reopenPending: () => setPendingReopen((n) => n + 1),
    openCrew: (id) => { setSelected(id); setPage(1) },
    closeCrew: () => setSelected(null),
    showToast: (m) => { setToast(m); setTimeout(() => setToast(null), 1800) },
  }), [page, selectedCrew, logOpen, alertsOpen, protocolsOpen, modulesOpen, sheetEmergency, toast, pendingReopen])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useUi() {
  const v = useContext(Ctx)
  if (!v) throw new Error('UiProvider missing')
  return v
}
