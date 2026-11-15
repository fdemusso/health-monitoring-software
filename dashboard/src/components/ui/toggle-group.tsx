import { cn } from '@/lib/utils'

export interface ToggleOption<T extends string> { value: T; label: string }

/** Single-select segmented control (shadcn ToggleGroup type="single" look). */
export function ToggleGroup<T extends string>({ value, onChange, options, className }: {
  value: T; onChange: (v: T) => void; options: ToggleOption<T>[]; className?: string
}) {
  return (
    <div role="radiogroup" className={cn('inline-flex flex-wrap gap-1.5', className)}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={cn(
            'h-9 rounded-full border px-4 text-[13px] font-medium transition active:scale-[.96]',
            o.value === value ? 'border-transparent bg-foreground text-primary-foreground' : 'border-white/15 text-muted-foreground',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
