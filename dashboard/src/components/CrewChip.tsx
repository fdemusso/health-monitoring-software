import { crewIdentity } from '@/domain/crewConfig'
import { moduleName } from '@/domain/names'

/** Astronaut tag: text stays neutral for contrast; the identity colour is the border. */
export function CrewChip({ id }: { id: string }) {
  const c = crewIdentity(id)
  return (
    <span
      className='inline-flex h-6 items-center justify-center rounded-full border-[1.5px] px-2.5 text-xs font-bold text-foreground'
      style={{ borderColor: c.color }}
    >
      {c.first}
    </span>
  )
}

export function ModuleChip({ id }: { id: string }) {
  return <span className="inline-flex h-6 items-center rounded-full border border-input px-2 text-xs font-bold text-foreground">{moduleName(id)}</span>
}
