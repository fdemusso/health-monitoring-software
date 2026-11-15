import { Check } from 'lucide-react'
import { useState } from 'react'
import { useUi } from '@/app/ui-context'
import { Button } from '@/components/ui/button'

/** Automatic mayday to Earth: one press, no panel. The link is not simulated; the press is acknowledged and the button stays disabled. Mount it with `key={emergency.id}` so every emergency has its own. */
export function ContactEarthButton({ size }: { size?: 'lg' }) {
  const ui = useUi()
  const [sent, setSent] = useState(false)
  return (
    <Button size={size} variant="outline" disabled={sent} onClick={() => { setSent(true); ui.showToast('Mayday sent to Earth') }}>
      {sent ? <><Check aria-hidden /> Earth notified</> : 'Contact Earth'}
    </Button>
  )
}
