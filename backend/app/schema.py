"""Tables added by feature modules (2026-11-25 onward). Each module creates its own tables at import with SQL that
works on both Postgres (production) and SQLite (the endpoint tests), then turns Row-Level Security on for them:
db.py only does that for tables that existed when it ran, and Supabase's public REST API can read any table without it."""
from app.db import conn


def ensure_tables(statements: list[str], tables: list[str]) -> None:
    for sql in statements:
        conn.execute(sql)
    conn.commit()
    for table in tables:
        try:
            row = conn.execute(
                "SELECT rowsecurity FROM pg_tables WHERE schemaname = 'public' AND tablename = ?", (table,)).fetchone()
        except Exception:
            continue  # SQLite (tests): no pg_tables, no RLS
        if row and not row[0]:
            # Only when it's off (a brand-new table), so a restart never waits on a lock held by the old server.
            try:
                conn.execute("SET lock_timeout = '5s'")
                conn.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
                conn.commit()
                print(f"Row-Level Security enabled on {table}")
            except Exception as e:
                print(f"Could not enable Row-Level Security on {table} (retried next start): {e}")
        try:
            conn.execute("RESET lock_timeout")
            conn.commit()
        except Exception:
            pass
