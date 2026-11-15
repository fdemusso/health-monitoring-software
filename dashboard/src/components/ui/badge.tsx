import type { HTMLAttributes } from 'react'
import { cn } from '@/lib/utils'
import type { Status } from '@/domain/status'

const TONE: Record<Status | 'muted', string> = {
  ok: 'text-ok border-ok/35 bg-ok/10',
  warn: 'text-warn border-warn/40 bg-warn/10',
  crit: 'text-crit border-crit/50 bg-crit/10',
  muted: 'text-muted-foreground border-white/15',
}

export function Badge({ tone = 'muted', className, ...props }: HTMLAttributes<HTMLSpanElement> & { tone?: Status | 'muted' }) {
  return <span className={cn('inline-flex items-center gap-1.5 rounded-full border px-3 py-[3px] text-[11px] font-medium tracking-[.06em]', TONE[tone], className)} {...props} />
}
