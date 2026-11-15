import { cva, type VariantProps } from 'class-variance-authority'
import type { ButtonHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

export const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 rounded-full font-medium transition active:scale-[.97] disabled:opacity-40 disabled:pointer-events-none border',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground border-transparent',
        outline: 'bg-transparent text-foreground border-white/20',
        danger: 'bg-crit text-white border-transparent',
        ghost: 'bg-transparent border-transparent',
      },
      size: { default: 'h-[54px] px-7 text-base', sm: 'h-[38px] px-4 text-[13px]', icon: 'size-11' },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)

export function Button({ className, variant, size, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants>) {
  return <button type="button" className={cn(buttonVariants({ variant, size }), className)} {...props} />
}
