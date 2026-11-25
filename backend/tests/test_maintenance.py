"""Maintenance mode: the owner switches the app off from the admin page; /admin, /health and /status keep working."""
from tests.test_admin import H, admin, login  # noqa: F401  (pytest fixture + helpers)
from tests.test_endpoints import client, signup  # noqa: F401

SITE = "https://www.timeframecalender.com"


def switch(c, on, **extra):
    return c.post("/admin/api/maintenance", json={"on": on, **extra}, headers=H)


def test_off_by_default_and_status_is_public(admin):
    assert admin.get("/status").json() == {"maintenance": False, "message": "", "until": None, "since": None}


def test_needs_admin_sign_in(admin):
    assert switch(admin, True).status_code == 401
    assert admin.get("/status").json()["maintenance"] is False


def test_switching_on_blocks_the_app_but_not_admin_or_health(admin):
    auth = signup(admin, "pat@example.com")
    assert login(admin).status_code == 200
    r = switch(admin, True, message="Upgrading the database.")
    assert r.status_code == 200 and r.json()["state"]["on"] is True

    blocked = admin.get("/auth/me", headers={**auth, "Origin": SITE})
    assert blocked.status_code == 503
    assert blocked.json()["maintenance"] is True and blocked.json()["message"] == "Upgrading the database."
    assert blocked.headers["access-control-allow-origin"] == SITE  # the website can read why
    assert admin.post("/auth/signup", json={"email": "new@example.com", "password": "correct-horse-battery"}).status_code == 503

    # A browser opening an API address directly (a sign-in link) is sent to the website's maintenance screen.
    nav = admin.get("/auth/google/login", headers={"Accept": "text/html"}, follow_redirects=False)
    assert nav.status_code == 302 and nav.headers["location"].startswith("https://")

    # CORS preflights, health checks, status and the admin page all still answer.
    pre = admin.options("/auth/me", headers={"Origin": SITE, "Access-Control-Request-Method": "GET",
                                              "Access-Control-Request-Headers": "authorization"})
    assert pre.status_code == 200
    assert admin.get("/health").status_code == 200 and admin.get("/").status_code == 200
    assert admin.get("/status").json()["maintenance"] is True
    assert admin.get("/admin/api/maintenance", headers=H).json()["on"] is True
    assert admin.get("/admin/api/overview", headers=H).json()["health"]["maintenance"] is True

    # Back on: everything works again, and both changes are in the audit log.
    assert switch(admin, False).json()["state"]["on"] is False
    assert admin.get("/auth/me", headers=auth).status_code == 200
    actions = [e["action"] for e in admin.get("/admin/api/audit", headers=H).json()["events"]]
    assert "maintenance_on" in actions and "maintenance_off" in actions


def test_switch_is_saved_in_the_database(admin):
    assert login(admin).status_code == 200
    r = switch(admin, True)
    assert r.status_code == 200, r.text
    import app.maintenance as m
    m._cache.update(at=0.0, state=None)  # like a restart: nothing in memory
    assert m.state()["on"] is True


def test_bad_input_is_refused(admin):
    login(admin)
    assert switch(admin, "yes").status_code == 400
    assert switch(admin, True, until="soon").status_code == 400
    assert switch(admin, True, until=1).status_code == 400  # in the past
    assert switch(admin, True, message="x" * 301).status_code == 400
    assert admin.get("/status").json()["maintenance"] is False
