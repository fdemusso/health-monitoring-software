import { cn } from '@/lib/utils'
import { useUi } from './ui-context'

export function Pager({ count = 2 }: { count?: number }) {
  const { page, setPage } = useUi()
  return (
    <div className="fixed bottom-4 left-1/2 z-[6] flex -translate-x-1/2 gap-2">
      {Array.from({ length: count }, (_, i) => (
        <button key={i} type="button" aria-label={`Page ${i + 1}`} onClick={() => setPage(i as 0 | 1)} className="grid h-6 w-8 place-items-center">
          <span className={cn('block h-1.5 rounded-full transition-all', i === page ? 'w-[26px] bg-foreground' : 'w-[6px] bg-muted-strong')} />
        </button>
      ))}
    </div>
  )
}
