import type { Emergency, NPCState } from '@/telemetry'

/** PLACEHOLDER texts: demonstration content, NOT medical guidance. */
export interface Protocol { id: string; title: string; steps: { title: string; hint: string }[] }

const HYPOXIA: Protocol = {
  id: 'hypoxia', title: 'Hypoxia / CO poisoning',
  steps: [
    { title: 'Check the sensor', hint: 'Make sure the pulse oximeter is positioned correctly.' },
    { title: 'Move to a healthy module', hint: 'Take the astronaut to a volume with a nominal atmosphere.' },
    { title: 'Supplemental oxygen', hint: 'Administer O₂ following the onboard procedure.' },
    { title: 'Recheck after 5 minutes', hint: 'Compare SpO₂ and HR with the initial values.' },
    { title: 'Teleconsult', hint: 'If there is no improvement, contact Earth when possible.' },
  ],
}
const HEAT: Protocol = {
  id: 'heat', title: 'Heat stress',
  steps: [
    { title: 'Stop the activity', hint: 'Let the astronaut rest.' },
    { title: 'Cool and hydrate', hint: 'Lower the module temperature, offer fluids.' },
    { title: 'Recheck core temperature', hint: 'After 10 minutes.' },
  ],
}
const ROUTINE: Protocol = {
  id: 'routine', title: 'Routine check',
  steps: [
    { title: 'Check vitals', hint: 'HR, SpO₂, core temperature within range.' },
    { title: 'Check the environment', hint: 'The astronaut’s module is within nominal limits.' },
  ],
}

const FIRE: Protocol = {
  id: 'fire', title: 'Fire',
  steps: [
    { title: 'Turn off ventilation and gas introduction', hint: 'The monitor does this automatically: verify it happened.' },
    { title: 'Discharge the extinguisher', hint: 'Aim the jet at the base of the fire.' },
    { title: 'Check whether the fire is out', hint: 'If it persists, evacuate to the return vehicle.' },
    { title: 'Evacuate if necessary', hint: 'Everyone to the lifeboat module, then close the hatches.' },
  ],
}
const DEPRESSURIZATION: Protocol = {
  id: 'depressurization', title: 'Pressure loss',
  steps: [
    { title: 'Isolate the module', hint: 'Close the hatches only if no one is left without an escape route.' },
    { title: 'Crew retreat', hint: 'With little time left, go to the return vehicle.' },
    { title: 'Locate and repair the leak', hint: 'Task for the systems engineer.' },
    { title: 'Restore pressure', hint: 'Reopen gas introduction once the leak is closed.' },
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
