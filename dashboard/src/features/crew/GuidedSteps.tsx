import { Check } from 'lucide-react'
import { useState } from 'react'
import { StatusBadge } from '@/components/ui/status-badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'
import type { Protocol } from './protocols'

export function GuidedSteps({ protocol }: { protocol: Protocol }) {
  const [done, setDone] = useState(0)
  const total = protocol.steps.length
  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="font-heading text-xl font-bold">{protocol.title}</h3>
        <StatusBadge status="warn">Contenuto dimostrativo</StatusBadge>
      </div>
      <Progress value={(done / total) * 100} />
      <p className="mb-2 mt-1 text-xs text-muted-foreground">{done >= total ? 'Completato' : `Passo ${done + 1} di ${total}`}</p>
      <ol className="space-y-2">
        {protocol.steps.map((s, i) => (
          <li
            key={s.title}
            className={cn(
              'flex gap-3 rounded-lg border p-2.5',
              i === done && 'border-foreground bg-card text-foreground',
              i > done && 'border-transparent text-muted-foreground',
              i < done && 'border-border bg-status-live-soft text-muted-foreground',
            )}
          >
            <span className={cn('mt-0.5 grid size-5 shrink-0 place-items-center rounded-full', i < done ? 'bg-status-live text-signal-on' : 'bg-muted-strong')}>{i < done ? <Check size={12} /> : <span className="text-xs">{i + 1}</span>}</span>
            <div><div className="text-sm font-medium">{s.title}</div>{i === done && <div className="text-xs text-muted-foreground">{s.hint}</div>}</div>
          </li>
        ))}
      </ol>
      {done < total && <Button variant="secondary" className="mt-3 w-full" onClick={() => setDone(done + 1)}>Passo completato</Button>}
    </div>
  )
}
