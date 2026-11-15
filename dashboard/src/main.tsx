import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/geist'
import '@fontsource-variable/lora'
import './index.css'
import App from './app/App.tsx'
import HologramHarness from './dev/HologramHarness.tsx'

const harness = new URLSearchParams(window.location.search).has('harness')

createRoot(document.getElementById('root')!).render(
  <StrictMode>{harness ? <HologramHarness /> : <App />}</StrictMode>,
)
