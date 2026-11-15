import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

/** Status tones from the design system. App statuses map as ok -> live, warn -> warning, crit -> danger. */
export type StatusTone = 'ok' | 'warn' | 'crit' | 'info' | 'neutral'

const TONE: Record<StatusTone, { chip: string; dot: string }> = {
  ok: { chip: 'bg-status-live-soft text-status-live-foreground', dot: 'bg-status-live' },
  warn: { chip: 'bg-status-warning-soft text-status-warning-foreground', dot: 'bg-status-warning' },
  crit: { chip: 'bg-status-danger-soft text-status-danger-foreground', dot: 'bg-status-danger' },
  info: { chip: 'bg-status-info-soft text-status-info-foreground', dot: 'bg-status-info' },
  neutral: { chip: 'bg-muted text-muted-foreground', dot: 'bg-muted-foreground' },
}

/** The only way to show a status as a chip: a dot plus a text label. */
export function StatusBadge({ status, className, children, ...props }: ComponentProps<'span'> & { status: StatusTone }) {
  const t = TONE[status]
  return (
    <span data-slot="status-badge" className={cn('inline-flex h-5 w-fit shrink-0 items-center gap-1.5 rounded-full px-2 text-xs font-medium whitespace-nowrap', t.chip, className)} {...props}>
      <i aria-hidden className={cn('size-[7px] rounded-full', t.dot)} />
      {children}
    </span>
  )
}
