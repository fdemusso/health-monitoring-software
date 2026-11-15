import { ToggleGroup as ToggleGroupPrimitive } from 'radix-ui'
import { cn } from '@/lib/utils'

export interface ToggleOption<T extends string> { value: T; label: string }

const ITEM = 'h-11 px-4 text-sm font-medium transition-colors outline-none focus-visible:z-10 focus-visible:ring-3 focus-visible:ring-ring/50'
const SOFT = 'rounded-control text-muted-foreground hover:bg-muted data-[state=on]:bg-muted-strong data-[state=on]:text-foreground'
/** Joined "button group": one bordered strip, items share the edges. */
const JOINED = 'border border-input first:rounded-l-control last:rounded-r-control not-first:-ml-px text-foreground hover:bg-muted data-[state=on]:bg-primary data-[state=on]:text-primary-foreground'

/** Single-select segmented control (shadcn ToggleGroup type="single"). `joined` draws a button group. */
export function ToggleGroup<T extends string>({ value, onChange, options, className, joined, size }: {
  value: T; onChange: (v: T) => void; options: ToggleOption<T>[]; className?: string; joined?: boolean
  /** `lg`: 48 px, for the main control of a page. The default is already 44 px (iPad). */
  size?: 'lg'
}) {
  return (
    <ToggleGroupPrimitive.Root
      type="single"
      value={value}
      // Radix emits '' when the active item is pressed again: keep the selection.
      onValueChange={(v) => { if (v) onChange(v as T) }}
      className={cn('inline-flex flex-wrap', !joined && 'gap-1', className)}
    >
      {options.map((o) => (
        <ToggleGroupPrimitive.Item key={o.value} value={o.value} className={cn(ITEM, joined ? JOINED : SOFT, size === 'lg' && 'h-12 px-5 text-base')}>{o.label}</ToggleGroupPrimitive.Item>
      ))}
    </ToggleGroupPrimitive.Root>
  )
}

/** Multi-select button group (shadcn ToggleGroup type="multiple"): outlined items, ink fill when selected. */
export function ToggleGroupMulti<T extends string>({ value, onChange, options, className, itemClassName }: {
  value: T[]; onChange: (v: T[]) => void; options: ToggleOption<T>[]; className?: string; itemClassName?: string
}) {
  return (
    <ToggleGroupPrimitive.Root type="multiple" value={value} onValueChange={(v) => onChange(v as T[])} className={cn('flex flex-wrap gap-1', className)}>
      {options.map((o) => (
        <ToggleGroupPrimitive.Item
          key={o.value}
          value={o.value}
          className={cn(ITEM, 'rounded-control border border-input text-foreground hover:bg-muted data-[state=on]:border-transparent data-[state=on]:bg-primary data-[state=on]:text-primary-foreground', itemClassName)}
        >
          {o.label}
        </ToggleGroupPrimitive.Item>
      ))}
    </ToggleGroupPrimitive.Root>
  )
}
