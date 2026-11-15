import { X } from 'lucide-react'
import { Dialog as DialogPrimitive } from 'radix-ui'
import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { DragHandles, useDraggable } from '@/lib/useDraggable'

/** Centered dialog (shadcn Dialog on Radix): scrim, focus trap, Esc to close. Movable by its corner handles. */
export function Dialog({ open, onClose, title, children, className, width = 640 }: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; className?: string; width?: number
}) {
  const { ref, offset, dragging, handleProps } = useDraggable<HTMLDivElement>(open)
  return (
    <DialogPrimitive.Root open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-scrim data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:duration-(--duration-enter) data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:duration-(--duration-exit)" />
        <DialogPrimitive.Content
          ref={ref}
          aria-describedby={undefined}
          // moved with left/top (not transform): the centering classes already use the translate property
          style={{ width, left: `calc(50% + ${offset.x}px)`, top: `calc(50% + ${offset.y}px)` }}
          className={cn(
            'fixed top-1/2 left-1/2 z-50 flex max-h-[88dvh] max-w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col rounded-lg border border-border bg-popover p-5 text-popover-foreground outline-none',
            'data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:duration-(--duration-enter) data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:duration-(--duration-exit)',
            className,
          )}
        >
          <div className="mb-4 flex items-center justify-between gap-3">
            <DialogPrimitive.Title className="font-heading text-xl font-bold">{title}</DialogPrimitive.Title>
            <DialogPrimitive.Close asChild>
              <Button variant="ghost" size="icon-lg" aria-label="Close"><X /></Button>
            </DialogPrimitive.Close>
          </div>
          <div className="no-scrollbar min-h-0 flex-1 overflow-x-hidden overflow-y-auto">{children}</div>
          <DragHandles handleProps={handleProps} dragging={dragging} />
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}
