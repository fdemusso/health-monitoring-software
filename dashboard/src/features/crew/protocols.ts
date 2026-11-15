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

const FIRE: Protocol = {
  id: 'fire', title: 'Incendio',
  steps: [
    { title: 'Spegni ventilazione e immissione di gas', hint: 'Il monitor lo fa in automatico: verifica che sia avvenuto.' },
    { title: 'Scarica l’estintore', hint: 'Dirigi il getto alla base del fuoco.' },
    { title: 'Controlla se il fuoco è spento', hint: 'Se persiste, evacua verso il veicolo di rientro.' },
    { title: 'Evacua se necessario', hint: 'Tutti nel modulo lifeboat, poi chiudi i portelli.' },
  ],
}
const DEPRESSURIZATION: Protocol = {
  id: 'depressurization', title: 'Perdita di pressione',
  steps: [
    { title: 'Isola il modulo', hint: 'Chiudi i portelli solo se nessuno resta senza via di fuga.' },
    { title: 'Ritirata dell’equipaggio', hint: 'Con tempo residuo breve, vai al veicolo di rientro.' },
    { title: 'Individua e ripara la perdita', hint: 'Compito dell’ingegnere di sistema.' },
    { title: 'Ripristina la pressione', hint: 'Riapri l’immissione di gas quando la perdita è chiusa.' },
  ],
}

/** Every protocol, for the library. */
export const PROTOCOLS: Protocol[] = [ROUTINE, HYPOXIA, HEAT, FIRE, DEPRESSURIZATION]

export function pickProtocol(npc: NPCState | undefined, emergencies: Emergency[]): Protocol {
  const e = emergencies.find((x) => x.state !== 'cleared' && x.kind === 'medical' && x.subject === npc?.id)
  if (e && (e.cause === 'hypoxia' || e.cause === 'co_poisoning')) return HYPOXIA
  if (e) return HYPOXIA
  if ((npc?.vitals.core_temp_c ?? 0) >= 37.8) return HEAT
  return ROUTINE
}
