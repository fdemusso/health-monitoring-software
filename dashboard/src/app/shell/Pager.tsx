import { cn } from '@/lib/utils'
import { useUi } from '../ui-context'

/** Dots at the bottom: one per page, `labels` are the page names. */
export function Pager({ labels }: { labels: string[] }) {
  const { page, setPage } = useUi()
  return (
    <div role="group" aria-label="Pages" className="fixed bottom-3 left-1/2 z-[6] flex -translate-x-1/2 gap-1">
      {labels.map((label, i) => (
        <button key={label} type="button" aria-label={`${label} page`} aria-current={i === page ? 'page' : undefined} onClick={() => setPage(i as 0 | 1)} className="grid h-9 w-11 place-items-center rounded-full outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
          <span className={cn('block h-1.5 rounded-full transition-all', i === page ? 'w-[26px] bg-foreground' : 'w-[6px] bg-muted-strong')} />
        </button>
      ))}
    </div>
  )
}
