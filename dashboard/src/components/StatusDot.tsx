import { cn } from '@/lib/utils'
import type { Status } from '@/domain/status'

const BG: Record<Status, string> = { ok: 'bg-status-live', warn: 'bg-status-warning', crit: 'bg-status-danger anim-ping' }
const NAME: Record<Status, string> = { ok: 'stabile', warn: 'attenzione', crit: 'critico' }

export function StatusDot({ status, className }: { status: Status; className?: string }) {
  return <span role="img" aria-label={NAME[status]} className={cn('inline-block size-[9px] shrink-0 rounded-full', BG[status], className)} />
}
