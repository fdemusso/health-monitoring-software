import { RotateNotice } from './feedback'
import { WarmupScreen } from './WarmupScreen'
import { Shell } from './Shell'
import { UiProvider } from './ui-context'

export default function App() {
  return <UiProvider><Shell /><WarmupScreen /><RotateNotice /></UiProvider>
}
