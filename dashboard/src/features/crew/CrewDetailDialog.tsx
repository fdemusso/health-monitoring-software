import { useUi } from '@/app/ui-context'
import { Dialog } from '@/components/ui/dialog'
import { crewIdentity } from '@/domain/crewConfig'
import { useTick } from '@/telemetry/useTelemetry'
import { CrewDetail } from './CrewDetail'

/**
 * The detail of one astronaut as a popover over whatever page is open: a tap outside (or Esc, or the X) closes it.
 * Another astronaut: close it and tap another pill.
 */
export function CrewDetailDialog() {
  const ui = useUi()
  const tick = useTick()
  const npc = ui.selectedCrew && tick ? tick.npcs[ui.selectedCrew] : undefined
  return (
    <Dialog open={!!npc} onClose={ui.closeCrew} title={npc ? crewIdentity(npc.id).person : 'Crew'} width={1040}>
      {npc && tick && (
        <CrewDetail npc={npc} tick={tick} />
      )}
    </Dialog>
  )
}
