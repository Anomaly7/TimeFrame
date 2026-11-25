import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import Root from './Root.jsx'
import { fetchStatus } from './maintenance.js'

// Service worker: push notifications and the offline copy of the app (public/sw.js).
// Chrome/Edge/Android offer "Install app": keep the prompt so the account menu can show it (see InstallItem).
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault()
  window.__tfInstallPrompt = e
  window.dispatchEvent(new Event('tf-installable'))
})

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
