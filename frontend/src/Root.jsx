import { useEffect, useState } from 'react'
import App from './App.jsx'
import Maintenance from './components/Maintenance.jsx'
import { onMaintenance } from './maintenance.js'
import BookingPage from './components/BookingPage.jsx'

// timeframecalender.com/<handle>: someone's public booking page (Pro), not the app.
const HANDLE_PATH = /^\/([a-z0-9][a-z0-9-]{1,28}[a-z0-9])\/?$/i

// Shows the maintenance screen instead of the app while the owner has TimeFrame switched off (admin page),
// including if it's switched off while someone is using it.
export default function Root({ initial }) {
  const [down, setDown] = useState(initial?.maintenance ? initial : null)
  useEffect(() => onMaintenance(setDown), [])
  if (down) return <Maintenance status={down} />
  const handle = window.location.pathname.match(HANDLE_PATH)?.[1]
  return handle ? <BookingPage handle={handle.toLowerCase()} /> : <App />
}
