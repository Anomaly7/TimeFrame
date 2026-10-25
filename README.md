# TimeFrame - Calendar Availability App

**Live Demo:**
👉 https://calender-app-one-xi.vercel.app

Google sign-in is restricted to pre-authorized test accounts while the app is in Google's unverified testing mode (message me for access). You don't need Google at all, though — **email/password sign-up works for anyone**.

---

## Overview

**TimeFrame** is a full-stack web application that helps users find the best available meeting times by combining multiple schedules.

Users sign in (Google or email/password), connect calendar sources, and instantly see **ranked free-time slots** — including a crowned "best" pick that favors times near the middle of the day and quieter days with fewer other commitments. The app is designed to solve a real coordination problem in a clean, user-friendly way.

---

## What the App Does

- Requires sign-in (Google OAuth or email/password) before showing any schedule data
- Imports a full year of busy events from Google Calendar
- Imports `.ics` calendar files exported from Outlook, Apple Calendar, etc.
- Allows users to manually add busy time blocks
- Merges overlapping schedules automatically
- Carves out candidate meeting slots of a user-chosen length, positioned near the middle of the day
- Ranks the top 3 candidate slots, with a crown 👑 on the best one
- Supports group scheduling via shareable links
- Offers Day, Week, and Month views with full navigation
- Saves schedules in a real database so data persists across devices and sessions

---

## Key Features

### Authentication & Security
- Sign in with Google OAuth, or create an account with email/password (bcrypt-hashed, never stored in plaintext)
- Every API request is authenticated with a signed session token — no calendar data is readable just by knowing someone's email or guessing a URL
- The app shows nothing (no data, no UI) until you're signed in

### Calendar Sources
- **Google Calendar** — a full year of events synced automatically on connect
- **.ics import** — upload a file exported from Outlook, Apple Calendar, or any other app
- **Manual entry** — add one-off busy blocks by hand

### Calendar Views
- Day, Week, and Month views, each with Previous / Today / Next navigation
- Click any day in Month view to jump straight into Day view for that date
- Settings let you customize day-start/day-end hours and exclude weekends

### Smart Availability Engine
- Merges all busy intervals into a single schedule per person
- Finds open gaps and proposes a meeting slot of exactly your chosen length (configurable in Settings), positioned as close to the middle of the day as that gap allows
- Between otherwise-similar options, favors the quieter day (fewer other events that day)
- Ranks the top 3 candidate slots; the best one gets a crown 👑

### Group Scheduling
- Create a short, easy-to-share group link
- Anyone who signs in via the link joins the group and sees everyone's merged availability
- Each member's own account controls what they share — no one needs anyone else's credentials

### Persistent State
- Backed by a real PostgreSQL database (Supabase), not just browser storage
- Schedules, group membership, and accounts persist across devices and redeploys

---

## Tech Stack

### Frontend
- React (Vite)
- JavaScript
- Deployed on **Vercel**

### Backend
- FastAPI (Python)
- PostgreSQL (hosted on Supabase)
- Google Calendar API (OAuth2)
- `bcrypt` for password hashing, `PyJWT` for session tokens
- `icalendar` / `recurring-ical-events` for `.ics` parsing
- Deployed on **Render**

### Testing
- `pytest` suite covering the scheduling algorithm and session-token auth (`backend/tests/`)

---

## Deployment

### Backend (Render) environment variables
| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | yes | Postgres (Supabase) connection string |
| `SESSION_SECRET` | yes | Random, **at least 32 characters**. The API refuses to start without it. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | yes | Google OAuth client |
| `REDIRECT_URI` | yes | `https://<api-host>/auth/callback` (must match the Google console) |
| `FRONTEND_URL` | no | Where sign-in redirects back to. Default `https://calender-app-one-xi.vercel.app` |
| `FRONTEND_ORIGINS` | no | Comma-separated origins allowed to call the API (CORS). Default: the Vercel URL + `http://localhost:5173` |
| `ALLOW_INSECURE_OAUTH` | local only | Set to `1` only when running the OAuth flow over plain `http://localhost` |

### Frontend (Vercel) environment variables
| Variable | Notes |
|---|---|
| `VITE_API_URL` | Backend URL. Default `https://calender-app-mm4q.onrender.com` |

### Running the tests
```
cd backend
pip install -r requirements-dev.txt
pytest
```
The endpoint tests use an in-memory SQLite stand-in, so no database is needed.

---

## Author

**Samuel Esebor**
UBC Computer Engineering student, Full-stack developer with ML and microelectronics background. Checkout my linkedin at linkedin.com/in/samuel-esebor.com
