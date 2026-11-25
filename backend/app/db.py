import contextvars
import os
import threading

import psycopg2
import psycopg2.extensions
from dotenv import load_dotenv

# Loaded here (not just in main.py) since this module connects to the
# database at import time, which can happen before main.py's own
# load_dotenv() call runs.
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")


# Set to a fresh object for every HTTP request (see main.py). Context vars
# follow a request into FastAPI's worker threads, so a connection can tell
# when a new request starts using it.
current_request = contextvars.ContextVar("current_request", default=None)


class _Connection:
    """sqlite3-style conn.execute(sql, params) / conn.commit() on top of
    psycopg2, with one real connection per worker thread.

    A single shared psycopg2 connection breaks in production: FastAPI runs
    sync endpoints on a thread pool (psycopg2 connections aren't safe to
    share across threads), one failed statement leaves the connection in
    "current transaction is aborted" so every later request fails, and a
    connection the database (or Supabase's pooler) drops is never replaced.
    Here each thread lazily opens its own connection, reconnects if it was
    closed, rolls back after any database error, and rolls back whatever a
    previous request left unfinished (it raised half-way) before a new
    request uses the connection, so partial writes are never committed."""

    def __init__(self, url):
        self._url = url
        self._local = threading.local()

    def _raw(self):
        raw = getattr(self._local, "raw", None)
        if raw is None or raw.closed:
            raw = psycopg2.connect(self._url, connect_timeout=10)
            self._local.raw = raw
            self._local.request = None
        rid = current_request.get()
        if rid is not None and self._local.request is not rid:
            if raw.status != psycopg2.extensions.STATUS_READY:
                raw.rollback()
            self._local.request = rid
        return raw

    def execute(self, sql, params=()):
        raw = self._raw()
        try:
            cur = raw.cursor()
            cur.execute(sql.replace("?", "%s"), params)
            return cur
        except psycopg2.Error:
            self._reset(raw)
            raise

    def commit(self):
        raw = self._raw()
        try:
            raw.commit()
        except psycopg2.Error:
            self._reset(raw)
            raise

    def _reset(self, raw):
        try:
            raw.rollback()
        except psycopg2.Error:
            try:
                raw.close()
            except psycopg2.Error:
                pass
            self._local.raw = None


conn = _Connection(DATABASE_URL)

conn.execute("""
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT
)
""")

# CREATE TABLE IF NOT EXISTS above won't retrofit a new column onto a
# users table that already exists in production.
existing_user_columns = {row[0] for row in conn.execute(
    "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'users'"
).fetchall()}
if "password_hash" not in existing_user_columns:
    conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
# True once Google has proven this person owns the email address.
if "email_verified" not in existing_user_columns:
    conn.execute("ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT FALSE")
# The name group members see on your blocks; NULL = the part of your email
# before the @.
if "display_name" not in existing_user_columns:
    conn.execute("ALTER TABLE users ADD COLUMN display_name TEXT")
# TimeFrame Pro (2026-11-20, see billing.py). plan = 'pro' or NULL (free); pro_source = early | coupon | stripe | manual.
if "plan" not in existing_user_columns:
    conn.execute("ALTER TABLE users ADD COLUMN plan TEXT")
    conn.execute("ALTER TABLE users ADD COLUMN pro_source TEXT")
    conn.execute("ALTER TABLE users ADD COLUMN stripe_customer TEXT")
    conn.execute("ALTER TABLE users ADD COLUMN stripe_sub TEXT")
    conn.execute("ALTER TABLE users ADD COLUMN pro_until BIGINT")
    # Everyone who signed up before Pro existed keeps it, free (Sam's decision). Runs once, at launch.
    conn.execute("UPDATE users SET plan = 'pro', pro_source = 'early'")
    conn.commit()

# When the account was made (unix seconds), for the owner's admin page. Accounts from before 2026-11-20 stay NULL
# (unknown); new ones get it from the column default, so no sign-up code has to change.
# (existing_user_columns only looks at public.users since 2026-11-20; before that it also saw Supabase's auth.users,
# which has its own created_at, so the column was never added.) Only touched when missing: an ALTER needs an exclusive
# lock, which waits behind the still-running old server during a deploy and made two deploys fail at startup. A failure
# here is logged, never fatal.
if "created_at" not in existing_user_columns:
    try:
        conn.execute("SET lock_timeout = '5s'")
        conn.execute("ALTER TABLE public.users ADD COLUMN IF NOT EXISTS created_at BIGINT")
        conn.execute("ALTER TABLE public.users ALTER COLUMN created_at SET DEFAULT (EXTRACT(EPOCH FROM now()))::bigint")
        conn.commit()
    except psycopg2.Error as e:
        print(f"Could not add users.created_at yet (will retry next start): {e}")
    finally:
        try:
            conn.execute("RESET lock_timeout")
            conn.commit()
        except psycopg2.Error:
            pass

# Owner admin page (admin.py): every sign-in attempt and change, kept for the audit trail and the lockouts.
conn.execute("""
CREATE TABLE IF NOT EXISTS admin_audit (
    at BIGINT,
    ip TEXT,
    action TEXT,
    detail TEXT
)
""")
conn.execute("CREATE INDEX IF NOT EXISTS admin_audit_at ON admin_audit (at)")
conn.commit()

# Owner admin page (Sam, 2026-11-24): banned emails can't sign in or sign up; a deleted account's
# old sign-ins stop working (tokens issued before at_ms are refused).
conn.execute("CREATE TABLE IF NOT EXISTS account_bans (email TEXT PRIMARY KEY, reason TEXT, at BIGINT)")
conn.execute("CREATE TABLE IF NOT EXISTS account_deletions (user_id TEXT PRIMARY KEY, at_ms BIGINT)")
conn.commit()

# One-time jobs that must never run twice (each name is recorded once it has run).
conn.execute("CREATE TABLE IF NOT EXISTS app_migrations (name TEXT PRIMARY KEY)")
conn.commit()
# Sam, 2026-11-20 (reverses the early-supporter grant): nobody keeps Pro. Every account goes back to Free; Pro is
# only the trial/checkout or the coupon from now on. Stripe ids are cleared too (they were test-mode ones).
if not conn.execute("SELECT 1 FROM app_migrations WHERE name = 'reset_all_pro_2026_11_20'").fetchone():
    conn.execute("UPDATE users SET plan = NULL, pro_source = NULL, stripe_customer = NULL, stripe_sub = NULL, pro_until = NULL")
    conn.execute("INSERT INTO app_migrations (name) VALUES ('reset_all_pro_2026_11_20')")
    conn.commit()

conn.execute("""
CREATE TABLE IF NOT EXISTS busy_times (
    id SERIAL PRIMARY KEY,
    user_id TEXT,
    start TEXT,
    end_time TEXT,
    source TEXT,
    raw_timezone TEXT,
    title TEXT
)
""")

conn.execute("""
CREATE TABLE IF NOT EXISTS groups (
    id TEXT PRIMARY KEY
)
""")

# Optional name members give a group link ("Robotics team"); NULL = unnamed.
existing_group_columns = {row[0] for row in conn.execute(
    "SELECT column_name FROM information_schema.columns WHERE table_name = 'groups'"
).fetchall()}
if "name" not in existing_group_columns:
    conn.execute("ALTER TABLE groups ADD COLUMN name TEXT")
# The group's admin (whoever created the link; NULL for links made before
# admins existed - any member can claim those) and the scheduling settings
# the admin chose (JSON), which everyone viewing the group uses.
if "owner" not in existing_group_columns:
    conn.execute("ALTER TABLE groups ADD COLUMN owner TEXT")
if "settings" not in existing_group_columns:
    conn.execute("ALTER TABLE groups ADD COLUMN settings TEXT")

# People an admin removed from a group; they can't rejoin with the link.
conn.execute("""
CREATE TABLE IF NOT EXISTS group_bans (
    group_id TEXT,
    user_id TEXT
)
""")

# Groups their admin deleted. The link stays dead: nobody can recreate a group with that id
# (they'd become admin of the old link everyone still has).
conn.execute("CREATE TABLE IF NOT EXISTS deleted_groups (id TEXT PRIMARY KEY, at_ms BIGINT)")

conn.execute("""
CREATE TABLE IF NOT EXISTS group_members (
    group_id TEXT,
    user_id TEXT
)
""")

# Calendar accounts connected without OAuth refresh tokens being kept
# (Apple via app-specific password, Notion): just "this user linked it".
conn.execute("""
CREATE TABLE IF NOT EXISTS calendar_links (
    user_id TEXT,
    source TEXT
)
""")

# Every request looks rows up by user / group; without these each lookup
# scans the whole table.
conn.execute("CREATE INDEX IF NOT EXISTS busy_times_user_source ON busy_times (user_id, source)")
conn.execute("CREATE INDEX IF NOT EXISTS group_members_group ON group_members (group_id)")

conn.commit()

# Supabase publishes every table in the public schema through its automatic
# REST API, which anyone holding the project's public (anon) key can call.
# This app never uses that API: the backend connects directly as the tables'
# owner, which Row-Level Security doesn't restrict. So turning RLS on with no
# policies closes the public API without changing anything for the app.
# Each table is done separately and failures are only logged, so this can
# never stop the server from starting.
for (_table,) in conn.execute(
    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND NOT rowsecurity"
).fetchall():
    try:
        conn.execute(f'ALTER TABLE public."{_table}" ENABLE ROW LEVEL SECURITY')
        conn.commit()
        print(f"Row-Level Security enabled on {_table}")
    except psycopg2.Error as e:
        print(f"Could not enable Row-Level Security on {_table}: {e}")
