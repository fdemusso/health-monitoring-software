import type { Emergency, NPCState } from '@/telemetry'

/** PLACEHOLDER texts: demonstration content, NOT medical guidance. */
export interface Protocol { id: string; title: string; steps: { title: string; hint: string }[] }

const HYPOXIA: Protocol = {
  id: 'hypoxia', title: 'Ipossia / intossicazione da CO',
  steps: [
    { title: 'Verifica il sensore', hint: 'Controlla che il pulsossimetro sia posizionato bene.' },
    { title: 'Sposta in un modulo sano', hint: 'Porta l’astronauta in un volume con atmosfera nominale.' },
    { title: 'Ossigeno supplementare', hint: 'Somministra O₂ secondo la procedura di bordo.' },
    { title: 'Ricontrolla dopo 5 minuti', hint: 'Confronta SpO₂ e FC con i valori iniziali.' },
    { title: 'Teleconsulto', hint: 'Se non migliora, contatta la Terra quando possibile.' },
  ],
}
const HEAT: Protocol = {
  id: 'heat', title: 'Stress termico',
  steps: [
    { title: 'Interrompi l’attività', hint: 'Fai riposare l’astronauta.' },
    { title: 'Raffredda e idrata', hint: 'Riduci la temperatura del modulo, offri liquidi.' },
    { title: 'Ricontrolla la temperatura core', hint: 'Dopo 10 minuti.' },
  ],
}
const ROUTINE: Protocol = {
  id: 'routine', title: 'Controllo di routine',
  steps: [
    { title: 'Controlla i vitali', hint: 'FC, SpO₂, temperatura core nei range.' },
    { title: 'Controlla l’ambiente', hint: 'Modulo dell’astronauta entro i limiti nominali.' },
  ],
}

export function pickProtocol(npc: NPCState | undefined, emergencies: Emergency[]): Protocol {
  const e = emergencies.find((x) => x.state !== 'cleared' && x.kind === 'medical' && x.subject === npc?.id)
  if (e && (e.cause === 'hypoxia' || e.cause === 'co_poisoning')) return HYPOXIA
  if (e) return HYPOXIA
  if ((npc?.vitals.core_temp_c ?? 0) >= 37.8) return HEAT
  return ROUTINE
}
