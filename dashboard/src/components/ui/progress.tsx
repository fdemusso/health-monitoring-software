import { Progress as ProgressPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

/** Signal-strong fill on a muted-strong track. */
export function Progress({ className, indicatorClassName, value = 0, ...props }: ComponentProps<typeof ProgressPrimitive.Root> & { indicatorClassName?: string }) {
  const v = Math.min(100, Math.max(0, value ?? 0))
  return (
    <ProgressPrimitive.Root data-slot="progress" value={v} className={cn('relative h-1.5 w-full overflow-hidden rounded-full bg-muted-strong', className)} {...props}>
      <ProgressPrimitive.Indicator data-slot="progress-indicator" className={cn('h-full bg-signal-strong transition-all', indicatorClassName)} style={{ width: `${v}%` }} />
    </ProgressPrimitive.Root>
  )
}
