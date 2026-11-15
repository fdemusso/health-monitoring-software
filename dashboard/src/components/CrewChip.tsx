import { crewIdentity } from '@/domain/crewConfig'

/** Astronaut tag: text stays neutral for contrast; the identity colour is the border. */
export function CrewChip({ id, large }: { id: string; large?: boolean }) {
  const c = crewIdentity(id)
  return (
    <span
      className={large ? 'inline-flex h-9 min-w-24 items-center justify-center rounded-full border-2 px-5 font-heading text-xl font-bold text-foreground' : 'inline-flex h-6 min-w-11 items-center justify-center rounded-full border-[1.5px] px-2 text-xs font-bold text-foreground'}
      style={{ borderColor: c.color }}
    >
      {c.label}
    </span>
  )
}

export function ModuleChip({ id }: { id: string }) {
  return <span className="inline-flex h-6 items-center rounded-full border border-input px-2 text-xs font-bold text-foreground">{id.toUpperCase()}</span>
}
