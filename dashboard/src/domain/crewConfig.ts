/** Static crew identity (scenarios/crew.yaml aliases). Sex is NOT here: it comes from `npc.sex`. */
export interface CrewIdentity {
  label: string
  alias: string
  name: string
  color: string
}

export const CREW: Record<string, CrewIdentity> = {
  cmd: { label: 'CMD', alias: 'ASTRO_01', name: 'Comandante', color: 'var(--id-cmd)' },
  eng: { label: 'ENG', alias: 'ASTRO_03', name: 'Ingegnere', color: 'var(--id-eng)' },
  med: { label: 'MED', alias: 'ASTRO_04', name: 'Medico', color: 'var(--id-med)' },
  bot: { label: 'BOT', alias: 'ASTRO_02', name: 'Botanico', color: 'var(--id-bot)' },
}

const FALLBACK_COLOR = 'hsl(215 10% 56%)'

export function crewIdentity(id: string): CrewIdentity {
  return CREW[id] ?? { label: id.toUpperCase(), alias: id, name: id, color: FALLBACK_COLOR }
}

/** Fixed display order. */
export const CREW_ORDER = ['cmd', 'eng', 'med', 'bot']
export const sortCrewIds = (ids: string[]) =>
  [...ids].sort((a, b) => {
    const ia = CREW_ORDER.indexOf(a), ib = CREW_ORDER.indexOf(b)
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b)
  })

export const sexToHologram = (sex: 'M' | 'F' | null | undefined) => (sex === 'F' ? 'female' : 'male') as 'male' | 'female'
