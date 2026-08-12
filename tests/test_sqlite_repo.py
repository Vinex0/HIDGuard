from hidguard.models.device_model import Device
from hidguard.models.input_event import InputEvent
from hidguard.models.session import Session


def test_save_and_query_device(repo):
    device = Device(id="046d:c31c:abc", vendor_name="Logitech")
    repo.save_device(device)

    row = repo._conn.execute("SELECT * FROM devices WHERE id = ?", (device.id,)).fetchone()
    assert row is not None


def test_save_session_then_update_on_end(repo):
    repo.save_device(Device(id="dev-1"))  # sessions.device_id is a foreign key
    session = Session.start(device_id="dev-1")
    repo.save_session(session)

    session.end()
    repo.save_session(session)

    row = repo._conn.execute(
        "SELECT disconnected_at FROM sessions WHERE id = ?", (str(session.id),)
    ).fetchone()
    assert row[0] == session.disconnected_at


def test_save_event(repo):
    repo.save_device(Device(id="dev-1"))
    session = Session.start(device_id="dev-1")
    repo.save_session(session)  # input_events.session_id is a foreign key
    event = InputEvent(session_id=session.id, type=1, code=30, value=1, timestamp=123.0)

    repo.save_event(event)

    row = repo._conn.execute("SELECT * FROM input_events WHERE session_id = ?", (str(session.id),)).fetchone()
    assert row is not None