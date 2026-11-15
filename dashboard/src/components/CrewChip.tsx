import { crewIdentity } from '@/domain/crewConfig'

export function CrewChip({ id }: { id: string }) {
  const c = crewIdentity(id)
  return (
    <span className="inline-flex h-6 min-w-11 items-center justify-center rounded-full border-[1.5px] px-[9px] text-[11px] font-bold tracking-[.1em]" style={{ color: c.color, borderColor: c.color }}>
      {c.label}
    </span>
  )
}

export function ModuleChip({ id }: { id: string }) {
  return <span className="inline-flex h-6 items-center rounded-full border border-white/25 px-[9px] text-[11px] font-bold tracking-[.1em] text-foreground">{id.toUpperCase()}</span>
}
