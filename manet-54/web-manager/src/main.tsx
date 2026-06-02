import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <div className="p-6">
      <h1 className="text-2xl font-bold">电台控制台</h1>
      <p className="text-muted-foreground mt-2">请访问 <a href="/radio/" className="underline">/radio/</a> 进入电台控制页面</p>
    </div>
  </StrictMode>,
)