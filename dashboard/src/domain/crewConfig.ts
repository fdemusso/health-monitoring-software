/** Static crew identity (scenarios/crew.yaml aliases). Sex is NOT here: it comes from `npc.sex`. */
export interface CrewIdentity {
  label: string
  alias: string
  /** First name, what the UI calls the person (chips, charts, titles). */
  first: string
  /** Role, as shown under the hologram. */
  name: string
  /** Fictional person (our own invention: no character from any book or film). */
  person: string
  /** CSS colour identifying the astronaut (`--crew-*` tokens). */
  color: string
}

const CREW: Record<string, CrewIdentity> = {
  cmd: { label: 'CMD', alias: 'ASTRO_01', first: 'Jonas', name: 'Commander', person: 'Jonas Reinholt', color: 'var(--crew-cmd)' },
  eng: { label: 'ENG', alias: 'ASTRO_03', first: 'Ines', name: 'Engineer', person: 'Ines Calderon', color: 'var(--crew-eng)' },
  med: { label: 'MED', alias: 'ASTRO_04', first: 'Hana', name: 'Medic', person: 'Hana Lindqvist', color: 'var(--crew-med)' },
  bot: { label: 'BOT', alias: 'ASTRO_02', first: 'Mark', name: 'Botanist', person: 'Mark Ellery', color: 'var(--crew-bot)' },
}

const FALLBACK_COLOR = 'var(--muted-foreground)'

export function crewIdentity(id: string): CrewIdentity {
  return CREW[id] ?? { label: id.toUpperCase(), alias: id, first: id.toUpperCase(), name: id, person: id, color: FALLBACK_COLOR }
}

/** Fixed display order. */
const CREW_ORDER = ['cmd', 'eng', 'med', 'bot']
export const sortCrewIds = (ids: string[]) =>
  [...ids].sort((a, b) => {
    const ia = CREW_ORDER.indexOf(a), ib = CREW_ORDER.indexOf(b)
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b)
  })

export const sexToHologram = (sex: 'M' | 'F' | null | undefined) => (sex === 'F' ? 'female' : 'male') as 'male' | 'female'
