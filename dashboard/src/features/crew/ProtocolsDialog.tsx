import { BookOpen, ChevronLeft } from 'lucide-react'
import { useState } from 'react'
import { useUi } from '@/app/ui-context'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { StatusDot } from '@/components/StatusDot'
import { emergencyTitle } from '@/domain/emergencyText'
import { fillText, openEmergencies } from '@/domain/procedures'
import { cn } from '@/lib/utils'
import type { EmergencyKind, ProcedureSpec } from '@/telemetry'
import { useCatalog, useTick } from '@/telemetry/useTelemetry'
import { EmergencyProtocol, PreviewProcedure } from './ProcedureView'

const KIND_LABEL: Record<EmergencyKind, string> = {
  depressurization: 'Air leak', fire: 'Fire', toxic: 'Toxic air', equipment: 'Equipment', medical: 'Medical', sensor_fault: 'Sensors', anomaly: 'Unexplained anomaly',
}

/** All procedures of the scenario, grouped by the kind of emergency. */
function Library({ catalog, onPick }: { catalog: ProcedureSpec[]; onPick: (id: string) => void }) {
  const kinds = [...new Set(catalog.map((p) => p.emergency))]
  return (
    <div className="space-y-4">
      {kinds.map((k) => (
        <section key={k} aria-label={KIND_LABEL[k] ?? k}>
          <h3 className="lbl mb-1.5">{KIND_LABEL[k] ?? k}</h3>
          <ul className="space-y-1.5">
            {catalog.filter((p) => p.emergency === k).map((p) => (
              <li key={p.id}><Button variant="outline" className="h-auto min-h-11 w-full justify-start whitespace-normal py-2 text-left" onClick={() => onPick(p.id)}>{fillText(p.title)}</Button></li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}

/**
 * Protocols. With an emergency open it proposes the right one (the checklist the backend runs for it, or the one it will start once the
 * emergency is confirmed); several emergencies: pick which one. Without one, or on request, the library of every procedure.
 */
export function ProtocolsDialog() {
  const ui = useUi()
  const tick = useTick()
  const catalog = useCatalog()
  const emergencies = tick ? openEmergencies(tick) : []
  const [picked, setPicked] = useState<string | null>(null)
  const [browse, setBrowse] = useState(false)
  const [libId, setLibId] = useState<string | null>(null)
  const current = emergencies.find((e) => e.id === picked) ?? emergencies[0]
  const spec = catalog.find((p) => p.id === libId)
  const showLibrary = browse || !current

  return (
    <Dialog open={ui.protocolsOpen} onClose={() => ui.setProtocolsOpen(false)} title="Protocols" width={640}>
      {showLibrary ? (
        spec ? (
          <>
            <Button variant="ghost" className="mb-3 -ml-2" onClick={() => setLibId(null)}><ChevronLeft /> All protocols</Button>
            <PreviewProcedure spec={spec} />
          </>
        ) : (
          <>
            {current ? (
              <Button variant="ghost" className="mb-3 -ml-2" onClick={() => setBrowse(false)}><ChevronLeft /> Back to the protocol for this emergency</Button>
            ) : (
              <p className="mb-4 text-sm text-muted-foreground">No emergency is open. When one is, the right protocol appears here by itself. Meanwhile, all of them:</p>
            )}
            {catalog.length ? <Library catalog={catalog} onPick={setLibId} /> : <p className="text-sm text-muted-foreground">No procedures loaded from the backend.</p>}
          </>
        )
      ) : tick && current && (
        <>
          {emergencies.length > 1 && (
            <ul className="mb-4 flex flex-wrap gap-2" aria-label="Open emergencies">
              {emergencies.map((e) => (
                <li key={e.id}>
                  <Button variant={e.id === current.id ? 'default' : 'outline'} size="sm" aria-pressed={e.id === current.id} onClick={() => setPicked(e.id)} className={cn('gap-2')}>
                    <StatusDot status={e.severity === 'critical' ? 'crit' : 'warn'} />{emergencyTitle(e)}
                  </Button>
                </li>
              ))}
            </ul>
          )}
          <EmergencyProtocol tick={tick} emergency={current} />
          <Button variant="ghost" className="mt-4 -ml-2" onClick={() => { setBrowse(true); setLibId(null) }}><BookOpen /> All protocols</Button>
        </>
      )}
    </Dialog>
  )
}
