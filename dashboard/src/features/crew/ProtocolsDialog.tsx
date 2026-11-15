import { useState } from 'react'
import { useUi } from '@/app/ui-context'
import { Dialog } from '@/components/ui/dialog'
import { ToggleGroup } from '@/components/ui/toggle-group'
import { GuidedSteps } from './GuidedSteps'
import { PROTOCOLS } from './protocols'

/** Protocol library: any procedure can be read and followed, with or without an emergency. */
export function ProtocolsDialog() {
  const ui = useUi()
  const [id, setId] = useState(PROTOCOLS[0].id)
  const protocol = PROTOCOLS.find((p) => p.id === id) ?? PROTOCOLS[0]
  return (
    <Dialog open={ui.protocolsOpen} onClose={() => ui.setProtocolsOpen(false)} title="Protocolli" width={640}>
      <ToggleGroup className="mb-4" value={id} onChange={setId} options={PROTOCOLS.map((p) => ({ value: p.id, label: p.title }))} />
      <GuidedSteps key={protocol.id} protocol={protocol} />
    </Dialog>
  )
}
