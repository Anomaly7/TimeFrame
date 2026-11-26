import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import Root from './Root.jsx'
import { fetchStatus } from './maintenance.js'
import { API_URL } from './config'

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

// Back from Google sign-in (#...&importing=1): the server imports the calendar in the background (2026-11-26).
// Keep the logo loading screen up with "Importing your Google Calendar…" until the next few weeks are in, then open
// the app; the rest of the year keeps importing and the calendar refreshes itself when it's done (tf-calendar-imported).
const bootHash = new URLSearchParams(window.location.hash.slice(1))
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
async function importStatus(token) {
  try {
    const r = await fetch(`${API_URL}/auth/import-status`, { headers: { Authorization: `Bearer ${token}` } })
    return r.ok ? await r.json() : null
  } catch {
    return null
  }
}
async function waitForImport() {
  const token = bootHash.get('token')
  if (bootHash.get('importing') !== '1' || !token) return
  const msg = document.getElementById('boot-msg')
  if (msg) msg.textContent = 'Importing your Google Calendar…'
  const deadline = Date.now() + 45000
  let s = null
  while (Date.now() < deadline) {
    s = await importStatus(token)
    if (!s || s.ready) break
    await sleep(600)
  }
  if (msg) msg.textContent = ''
  if (s && s.state === 'running') {
    ;(async () => {
      for (let i = 0; i < 60; i++) {
        await sleep(3000)
        const t = await importStatus(token)
        if (!t || t.state !== 'running') {
          window.dispatchEvent(new Event('tf-calendar-imported'))
          return
        }
      }
    })()
  }
}

// Maintenance check and the import wait run side by side (the logo loading screen in index.html stays up meanwhile).
Promise.all([fetchStatus(), waitForImport()]).then(([status]) => {
  createRoot(document.getElementById('root')).render(
    <StrictMode>
      <Root initial={status} />
    </StrictMode>,
  )
})
