# Presence of this file makes pytest add this directory (backend/) to
# sys.path regardless of the working directory pytest is invoked from,
# so "from app.xxx import yyy" resolves the same way it does for uvicorn.

import os

# The server's background loops (Google auto-sync, meeting reminders) never run in tests.
os.environ.setdefault("DISABLE_BACKGROUND_JOBS", "1")
