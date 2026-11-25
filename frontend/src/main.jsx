import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import Root from './Root.jsx'
import { fetchStatus } from './maintenance.js'

// Service worker: push notifications and the offline copy of the app (public/sw.js).
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}))
}

// Ask the API whether TimeFrame is in maintenance first (the logo loading screen in index.html stays up meanwhile).
fetchStatus().then((status) => {
  createRoot(document.getElementById('root')).render(
    <StrictMode>
      <Root initial={status} />
    </StrictMode>,
  )
})
