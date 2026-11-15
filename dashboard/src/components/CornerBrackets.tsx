/** Holographic corner brackets; parent must be `relative`. */
export function CornerBrackets({ color = 'color-mix(in oklab, var(--chart-1) 70%, transparent)' }: { color?: string }) {
  const base = 'pointer-events-none absolute size-4 border-[1.5px]'
  return (
    <>
      <span aria-hidden className={`${base} -left-px -top-px rounded-tl-md border-r-0 border-b-0`} style={{ borderColor: color }} />
      <span aria-hidden className={`${base} -bottom-px -right-px rounded-br-md border-l-0 border-t-0`} style={{ borderColor: color }} />
    </>
  )
}
