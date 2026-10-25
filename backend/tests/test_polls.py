from tests.test_endpoints import client, signup  # noqa: F401  (client is a pytest fixture)

NEW_POLL = {"title": "Project sync", "dates": ["2031-03-04", "2031-03-03"], "start": "09:00",
            "end": "11:00", "slot_minutes": 30, "timezone": "America/Vancouver"}


def make_poll(client, headers):
    r = client.post("/polls", json=NEW_POLL, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_creating_a_poll_requires_sign_in(client):
    assert client.post("/polls", json=NEW_POLL).status_code == 401


def test_poll_grid_covers_every_date_and_slot(client):
    poll_id = make_poll(client, signup(client, "host@example.com"))
    poll = client.get(f"/polls/{poll_id}").json()
    assert poll["dates"] == ["2031-03-03", "2031-03-04"]
    assert len(poll["cells"]) == 2 * 4
    assert poll["cells"][0] == "2031-03-03T09:00" and poll["cells"][-1] == "2031-03-04T10:30"


def test_guests_respond_with_a_name_and_can_edit_with_their_token(client):
    poll_id = make_poll(client, signup(client, "host@example.com"))
    r = client.post(f"/polls/{poll_id}/respond", json={"name": "Jo", "slots": ["2031-03-03T09:00", "bogus"]})
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["slots"] == ["2031-03-03T09:00"]  # cells outside the grid are dropped
    assert first["edit_token"]

    r = client.post(f"/polls/{poll_id}/respond",
                    json={"name": "Jo", "slots": ["2031-03-04T10:30"], "edit_token": first["edit_token"]})
    assert r.json()["id"] == first["id"]
    responses = client.get(f"/polls/{poll_id}").json()["responses"]
    assert responses == [{"id": first["id"], "name": "Jo", "slots": ["2031-03-04T10:30"]}]


def test_a_second_guest_cannot_take_an_existing_name(client):
    poll_id = make_poll(client, signup(client, "host@example.com"))
    client.post(f"/polls/{poll_id}/respond", json={"name": "Jo", "slots": []})
    r = client.post(f"/polls/{poll_id}/respond", json={"name": "jo", "slots": []})
    assert r.status_code == 409


def test_signed_in_responses_never_expose_the_email(client):
    host = signup(client, "host@example.com")
    poll_id = make_poll(client, host)
    client.post(f"/polls/{poll_id}/respond", json={"name": "Host", "slots": []}, headers=host)
    client.post(f"/polls/{poll_id}/respond", json={"name": "Host renamed", "slots": []}, headers=host)
    body = client.get(f"/polls/{poll_id}").text
    assert "host@example.com" not in body
    assert len(client.get(f"/polls/{poll_id}").json()["responses"]) == 1


def test_autofill_marks_only_cells_clear_of_saved_busy_times(client):
    host = signup(client, "host@example.com")
    poll_id = make_poll(client, host)
    # Save a busy block 09:30-10:30 on Mar 3 through the normal merge endpoint.
    block = [[{"start": "2031-03-03T09:30", "end": "2031-03-03T10:30"}]]
    client.post("/availability/merge?timezone=America/Vancouver", json=block, headers=host)
    free = client.get(f"/polls/{poll_id}/autofill", headers=host).json()["slots"]
    assert "2031-03-03T09:00" in free and "2031-03-03T10:30" in free
    assert "2031-03-03T09:30" not in free and "2031-03-03T10:00" not in free
    assert all(c in free for c in ["2031-03-04T09:00", "2031-03-04T10:30"])


def test_unknown_poll_is_404(client):
    assert client.get("/polls/doesnotexist").status_code == 404
    assert client.get("/polls/bad!id").status_code == 404


def test_signing_in_takes_over_your_guest_answer(client):
    host = signup(client, "host@example.com")
    poll_id = make_poll(client, host)
    guest = client.post(f"/polls/{poll_id}/respond", json={"name": "Sam", "slots": ["2031-03-03T09:00"]}).json()
    r = client.post(f"/polls/{poll_id}/respond",
                    json={"name": "Sam", "slots": ["2031-03-03T09:30"], "edit_token": guest["edit_token"]}, headers=host)
    assert r.status_code == 200, r.text
    responses = client.get(f"/polls/{poll_id}").json()["responses"]
    assert len(responses) == 1 and responses[0]["slots"] == ["2031-03-03T09:30"]
