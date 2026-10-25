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
    "SELECT column_name FROM information_schema.columns WHERE table_name = 'users'"
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

conn.execute("""
CREATE TABLE IF NOT EXISTS group_members (
    group_id TEXT,
    user_id TEXT
)
""")

# Every request looks rows up by user / group; without these each lookup
# scans the whole table.
conn.execute("CREATE INDEX IF NOT EXISTS busy_times_user_source ON busy_times (user_id, source)")
conn.execute("CREATE INDEX IF NOT EXISTS group_members_group ON group_members (group_id)")

conn.commit()
