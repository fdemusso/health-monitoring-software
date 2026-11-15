import { X } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

/** Minimal side sheet (no Radix): backdrop, Esc to close. */
export function Sheet({ open, onClose, title, children, className, width = 420 }: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; className?: string; width?: number
}) {
  useEffect(() => {
    if (!open) return
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <aside role="dialog" aria-label={title} style={{ width }} className={cn('absolute right-0 top-0 flex h-full max-w-full flex-col border-l bg-card p-5 animate-in slide-in-from-right duration-200', className)}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="lbl">{title}</h2>
          <button type="button" aria-label="Chiudi" onClick={onClose} className="grid size-11 place-items-center rounded-full border border-white/15"><X size={18} /></button>
        </div>
        <div className="no-scrollbar min-h-0 flex-1 overflow-y-auto">{children}</div>
      </aside>
    </div>
  )
}
