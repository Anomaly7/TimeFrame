# TimeFrame - Calendar Availability App

**Live Demo:**
👉 https://www.timeframecalender.com

Google sign-in is restricted to pre-authorized test accounts while the app is in Google's unverified testing mode (message me for access). You don't need Google at all, though — **email/password sign-up works for anyone**.

---

## Overview

**TimeFrame** is a full-stack web application that helps users find the best available meeting times by combining multiple schedules.

Users sign in (Google or email/password), connect calendar sources, and instantly see **ranked free-time slots** — including a crowned "best" pick that favors times near the middle of the day and quieter days with fewer other commitments. The app is designed to solve a real coordination problem in a clean, user-friendly way.

---

## What the App Does

- Requires sign-in (Google, Notion or email/password) before showing any schedule data
- Imports a full year of busy events from Google Calendar, from every calendar you have turned on (not just the main one)
- Sign in with, or connect, Apple Calendar (iCloud) using an app-specific password
- Imports timed entries from Notion databases you share with it
- Imports `.ics` calendar files exported from Outlook, Apple Calendar, etc. (several at once)
- Allows users to manually add busy time blocks
- Merges overlapping schedules automatically
- Carves out candidate meeting slots of a user-chosen length, positioned near the middle of the day
- Ranks the top 3 candidate slots, with a crown 👑 on the best one
- Supports group scheduling via shareable links
- Offers Day, Week, and Month views with full navigation
- Saves schedules in a real database so data persists across devices and sessions
- **Free for everyone:** every account gets every feature, Pro included

---

## Newer Features

- **Google auto-sync:** "Sync now", a "last updated" label, and an optional re-sync every 3 hours. The first Google import runs in the background behind a loading screen.
- **Book the slot:** book a best time for the group. It shows as "Booked" and counts as busy in members' other groups (without a title). Add it to Google Calendar or download an `.ics`.
- **Polls:** an admin proposes 2–5 times, members tap to vote, and the winner is booked.
- **Guest links:** people can join a group with just a name, no account needed. Admins can turn guest joining off.
- **Smarter suggestions:** "Almost works" times (everyone but one person), a travel buffer, and a weekly recurring-time finder.
- **Booking page:** a public `timeframecalender.com/<handle>` page where anyone can book time with you.
- **Group notes and notifications:** pinned notes, a notification bell, 1-hour reminders, and Web Push.
- **Installable app (PWA):** works offline with your saved calendar, plus a phone-first layout.
- **Chrome extension** (`extension/`): a toolbar popup with the best free times this week for any group, using the site's sign-in.
- **Owner admin page and maintenance mode:** accounts, health, bans and account deletion, plus a switch that puts the whole app into maintenance with a message.

---

## Key Features

### Authentication & Security
- Sign in with Google OAuth, or create an account with email/password (bcrypt-hashed, never stored in plaintext)
- Every API request is authenticated with a signed session token — no calendar data is readable just by knowing someone's email or guessing a URL
- The app shows nothing (no data, no UI) until you're signed in

### Calendar Sources
- **Google Calendar** — a full year of events from every calendar shown in your Google Calendar (classes, work, personal...), synced automatically on connect; holiday and birthday calendars and all-day events are skipped
- **Apple Calendar** — every iCloud calendar (not Reminders), a year ahead, via CalDAV with your Apple ID email and an app-specific password; the password is used once for the import and never stored. Events marked "Free" are skipped
- **Notion** — sign in with Notion or connect it to your account; imports pages with a date-and-time property from the databases you share with TimeFrame (date-only entries such as deadlines aren't busy time; a start with no end counts as 1 hour). The Notion token is used once and never stored
- **.ics import** — upload one or more files exported from Outlook, Apple Calendar, or any other app
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
- `pytest` suite (~130 tests) covering the scheduling algorithm, session-token auth, billing, the newer features and a security audit (`backend/tests/`)

---

## Deployment

### Backend (Render) environment variables
| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | yes | Postgres (Supabase) connection string |
| `SESSION_SECRET` | yes | Random, **at least 32 characters**. The API refuses to start without it. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | yes | Google OAuth client |
| `REDIRECT_URI` | yes | `https://<api-host>/auth/callback` (must match the Google console) |
| `NOTION_CLIENT_ID` / `NOTION_CLIENT_SECRET` | no | Notion public integration (Notion sign-in/connect is hidden behind an error until set) |
| `NOTION_REDIRECT_URI` | no | `https://<api-host>/notion/callback` (must match the integration's redirect URI) |
| `FRONTEND_URL` | no | Where sign-in redirects back to. Default `https://www.timeframecalender.com` |
| `FRONTEND_ORIGINS` | no | Comma-separated origins allowed to call the API (CORS). Default: the Vercel URL + `http://localhost:5173` |
| `ADMIN_PASSWORD` | no | Owner admin page at `/admin` (16+ characters; 404 until set) |
| `OWNER_NTFY_TOPIC` | no | Phone alerts for admin sign-ins and other owner events |
| `GOOGLE_TOKEN_KEY` | no | Turns on Google auto-sync (encrypts stored refresh tokens). Optional server keys can be generated with `python backend/keys_setup.py` |
| `VAPID_PRIVATE_KEY` | no | Turns on Web Push notifications |
| `TIMEFRAME_FREE_FOR_ALL` | no | On by default (everyone gets Pro). Set to `0` to bring paid Pro back |
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
Computer engineering student at UBC Okanagan. [Portfolio](https://samuel-esebor.vercel.app) · [LinkedIn](https://www.linkedin.com/in/samuel-esebor)
