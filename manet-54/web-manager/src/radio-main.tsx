import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { RadioDeviceControl } from './sections/RadioDeviceControl'

createRoot(document.getElementById('root-radio')!).render(
  <StrictMode>
    <div className="min-h-screen bg-background p-6">
      <RadioDeviceControl />
    </div>
  </StrictMode>,
)