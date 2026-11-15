import { X } from 'lucide-react'
import { Dialog as SheetPrimitive } from 'radix-ui'
import type { ComponentProps, ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'

/** Side sheet (shadcn Sheet on Radix Dialog): focus trap, Esc and scrim included. `modeless`: no scrim and the page behind stays usable (closes only with X or Esc). */
export function Sheet({ open, onClose, title, children, className, width = 420, modeless }: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; className?: string; width?: number; modeless?: boolean
}) {
  return (
    <SheetPrimitive.Root open={open} onOpenChange={(o) => { if (!o) onClose() }} modal={!modeless}>
      <SheetPrimitive.Portal>
        {!modeless && <SheetOverlay />}
        <SheetPrimitive.Content
          aria-describedby={undefined}
          onInteractOutside={modeless ? (e) => e.preventDefault() : undefined}
          style={{ width: `${width / 16}rem` }}
          className={cn(
            'fixed inset-y-0 right-0 z-50 flex h-full max-w-full flex-col border-l border-border bg-popover p-5 text-popover-foreground outline-none',
            modeless && 'shadow-2xl',
            'data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:slide-in-from-right data-[state=open]:duration-(--duration-enter)',
            'data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:slide-out-to-right data-[state=closed]:duration-(--duration-exit)',
            className,
          )}
        >
          <div className="mb-4 flex items-center justify-between gap-3">
            <SheetPrimitive.Title className="font-heading text-xl font-bold">{title}</SheetPrimitive.Title>
            <SheetPrimitive.Close asChild>
              <Button variant="ghost" size="icon-lg" aria-label="Close"><X /></Button>
            </SheetPrimitive.Close>
          </div>
          <ScrollArea className="min-h-0 flex-1">{children}</ScrollArea>
        </SheetPrimitive.Content>
      </SheetPrimitive.Portal>
    </SheetPrimitive.Root>
  )
}

function SheetOverlay({ className, ...props }: ComponentProps<typeof SheetPrimitive.Overlay>) {
  return (
    <SheetPrimitive.Overlay
      className={cn('fixed inset-0 z-50 bg-scrim data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:duration-(--duration-enter) data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:duration-(--duration-exit)', className)}
      {...props}
    />
  )
}
