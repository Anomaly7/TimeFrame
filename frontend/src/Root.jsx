import { useEffect, useState } from 'react'
import App from './App.jsx'
import Maintenance from './components/Maintenance.jsx'
import { onMaintenance } from './maintenance.js'

// Shows the maintenance screen instead of the app while the owner has TimeFrame switched off (admin page),
// including if it's switched off while someone is using it.
export default function Root({ initial }) {
  const [down, setDown] = useState(initial?.maintenance ? initial : null)
  useEffect(() => onMaintenance(setDown), [])
  return down ? <Maintenance status={down} /> : <App />
}
