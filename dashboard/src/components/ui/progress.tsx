export function Progress({ value }: { value: number }) {
  return (
    <div role="progressbar" aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={100} className="h-[3px] w-full overflow-hidden rounded-full bg-white/10">
      <div className="h-full bg-foreground transition-all" style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
    </div>
  )
}
