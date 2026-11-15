import { Check } from 'lucide-react'
import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
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
        <h3 className="text-base font-medium">{protocol.title}</h3>
        <Badge tone="warn">Contenuto dimostrativo</Badge>
      </div>
      <Progress value={(done / total) * 100} />
      <p className="mb-2 mt-1 text-xs text-muted-foreground">{done >= total ? 'Completato' : `Passo ${done + 1} di ${total}`}</p>
      <ol className="space-y-2">
        {protocol.steps.map((s, i) => (
          <li
            key={s.title}
            className={cn(
              'flex gap-3 rounded-xl border p-2.5',
              i === done && 'border-white/60 text-foreground',
              i > done && 'border-transparent text-muted-foreground',
              i < done && 'border-ok/40 bg-ok/[.06] text-muted-foreground shadow-[0_0_14px_hsl(152_66%_52%/.22)]',
            )}
          >
            <span className={cn('mt-0.5 grid size-5 shrink-0 place-items-center rounded-full', i < done ? 'bg-ok/20 text-ok' : 'bg-white/15')}>{i < done ? <Check size={12} /> : <span className="text-[10px]">{i + 1}</span>}</span>
            <div><div className="text-sm">{s.title}</div>{i === done && <div className="text-xs text-muted-foreground">{s.hint}</div>}</div>
          </li>
        ))}
      </ol>
      {done < total && <Button size="sm" className="mt-3 w-full" onClick={() => setDone(done + 1)}>Passo completato</Button>}
    </div>
  )
}
