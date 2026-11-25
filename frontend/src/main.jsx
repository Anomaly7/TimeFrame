import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import Root from './Root.jsx'
import { fetchStatus } from './maintenance.js'

// Ask the API whether TimeFrame is in maintenance first (the logo loading screen in index.html stays up meanwhile).
fetchStatus().then((status) => {
  createRoot(document.getElementById('root')).render(
    <StrictMode>
      <Root initial={status} />
    </StrictMode>,
  )
})
