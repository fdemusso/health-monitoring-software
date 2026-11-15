import { Moon, Sun } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'

const KEY = 'ares3-theme'

/** Light/dark switch. The initial class is set in index.html before first paint. */
export function ThemeToggle() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))
  const toggle = () => {
    const next = !dark
    document.documentElement.classList.toggle('dark', next)
    try { localStorage.setItem(KEY, next ? 'dark' : 'light') } catch { /* private mode */ }
    setDark(next)
  }
  return (
    <Button variant="ghost" size="icon" aria-label={dark ? 'Tema chiaro' : 'Tema scuro'} onClick={toggle}>
      {dark ? <Sun /> : <Moon />}
    </Button>
  )
}
