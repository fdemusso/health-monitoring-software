import { cva, type VariantProps } from 'class-variance-authority'
import { Slot } from 'radix-ui'
import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

export const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-control border border-transparent font-medium whitespace-nowrap transition-colors outline-none select-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-5",
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground hover:bg-primary/90',
        outline: 'border-input bg-transparent text-foreground hover:bg-muted',
        secondary: 'bg-muted text-secondary-foreground hover:bg-muted-strong',
        ghost: 'bg-transparent text-foreground hover:bg-muted',
        destructive: 'bg-status-danger-soft text-status-danger-foreground hover:bg-status-danger/25',
        link: 'text-foreground underline-offset-4 hover:underline',
      },
      size: {
        // touch first: the default is 44 px at the base size (Apple HIG minimum), `lg` for the main action of a card
        default: 'h-11 px-4 text-base',
        xs: 'h-8 px-2.5 text-xs',
        sm: 'h-9 px-3 text-sm',
        lg: 'h-12 px-5 text-base',
        icon: 'size-11',
        'icon-xs': 'size-8',
        'icon-sm': 'size-9',
        'icon-lg': 'size-12',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)

export function Button({ className, variant, size, asChild = false, type = 'button', ...props }: ComponentProps<'button'> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : 'button'
  return <Comp data-slot="button" type={asChild ? undefined : type} className={cn(buttonVariants({ variant, size }), className)} {...props} />
}
