from app.db import conn

# Rows per INSERT statement. Each statement is one round trip to the database
# (Render in Oregon -> Supabase in Virginia is ~70 ms), so saving a year of
# Google events one row at a time took over a minute; a few multi-row inserts
# take well under a second. 500 rows x 6 columns also stays far below
# SQLite's (tests) and Postgres's limits on bound parameters.
CHUNK = 500


def insert_busy_rows(rows):
    """rows: (user_id, start_iso, end_iso, source, raw_timezone, title) tuples.
    The caller commits."""
    rows = list(rows)
    for i in range(0, len(rows), CHUNK):
        chunk = rows[i:i + CHUNK]
        placeholders = ", ".join(["(?, ?, ?, ?, ?, ?)"] * len(chunk))
        conn.execute(
            "INSERT INTO busy_times (user_id, start, end_time, source, raw_timezone, title) VALUES " + placeholders,
            tuple(v for row in chunk for v in row),
        )
