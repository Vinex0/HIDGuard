from uuid import uuid4

from hidguard.models.detection import Detection, RuleHit
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

    row = repo._conn.execute(
        "SELECT * FROM input_events WHERE session_id = ?", (str(session.id),)
    ).fetchone()
    assert row is not None


def test_get_session_round_trip(repo):
    """get_session must hand back a real Session, not a raw row: the detection loop
    reads sessions this way to decide what to re-analyse."""
    repo.save_device(Device(id="dev-1"))
    session = Session.start(device_id="dev-1")
    repo.save_session(session)

    fetched = repo.get_session(session.id)

    assert fetched is not None
    assert fetched.id == session.id
    assert fetched.connected_at == session.connected_at


def test_get_session_missing_returns_none(repo):
    assert repo.get_session(uuid4()) is None


def test_list_session_newest_first_and_limit(repo):
    """The dashboard's session list is meant to show the newest sessions first,
    capped by limit."""
    repo.save_device(Device(id="dev-1"))
    sessions = [
        Session(id=uuid4(), device_id="dev-1", connected_at=t) for t in (100.0, 200.0, 300.0)
    ]
    for session in sessions:
        repo.save_session(session)

    all_sessions = repo.list_session()
    assert [s.connected_at for s in all_sessions] == [300.0, 200.0, 100.0]

    limited = repo.list_session(limit=2)
    assert [s.connected_at for s in limited] == [300.0, 200.0]


def test_get_events_for_session_ordered_by_id(repo):
    """Every event in a SYN group shares an identical timestamp, so callers rely on
    insertion (id) order rather than timestamp order to reconstruct the sequence."""
    repo.save_device(Device(id="dev-1"))
    session = Session.start(device_id="dev-1")
    repo.save_session(session)

    for code in (30, 31, 32, 33):
        repo.save_event(
            InputEvent(session_id=session.id, type=1, code=code, value=1, timestamp=1.0)
        )

    events = repo.get_events_for_session(session.id)

    assert [e.code for e in events] == [30, 31, 32, 33]


def test_get_device_round_trip(repo):
    device = Device(id="046d:c31c:abc", vendor_name="Logitech")
    repo.save_device(device)

    fetched = repo.get_device(device.id)

    assert fetched is not None
    assert fetched.id == device.id
    assert fetched.vendor_name == "Logitech"


def test_get_device_missing_returns_none(repo):
    assert repo.get_device("does-not-exist") is None


def test_list_devices(repo):
    repo.save_device(Device(id="dev-1"))
    repo.save_device(Device(id="dev-2"))

    devices = repo.list_devices()

    assert {d.id for d in devices} == {"dev-1", "dev-2"}


def test_save_and_get_detection(repo):
    """hits must survive the round trip through the reasons JSON column, otherwise
    the dashboard can't show which rules fired."""
    repo.save_device(Device(id="dev-1"))
    session = Session.start(device_id="dev-1")
    repo.save_session(session)
    detection = Detection(
        session_id=session.id,
        score=70,
        verdict="malicious",
        hits=[
            RuleHit(rule="instant_typing", score=40, reason="typed 300ms after enumeration"),
            RuleHit(rule="superhuman_speed", score=30, reason="avg interkey delay 12ms"),
        ],
    )

    repo.save_detection(detection)
    fetched = repo.get_detection(session.id)

    assert fetched is not None
    assert fetched.score == 70
    assert fetched.verdict == "malicious"
    assert [h.rule for h in fetched.hits] == ["instant_typing", "superhuman_speed"]


def test_get_detection_missing_returns_none(repo):
    assert repo.get_detection(uuid4()) is None


def test_save_detection_upserts(repo):
    """The detection loop re-analyses each active session every couple of seconds,
    so re-scoring must update the existing row rather than duplicate it."""
    repo.save_device(Device(id="dev-1"))
    session = Session.start(device_id="dev-1")
    repo.save_session(session)
    repo.save_detection(Detection(session_id=session.id, score=20, verdict="benign", hits=[]))

    repo.save_detection(Detection(session_id=session.id, score=80, verdict="malicious", hits=[]))

    all_detections = repo.list_detections()
    assert len(all_detections) == 1
    assert all_detections[0].score == 80
    assert all_detections[0].verdict == "malicious"


def test_save_detection_keeps_the_newer_row_against_a_stale_write(repo):
    """A late scorer snapshot must not clobber a fresher detection.

    The scorer works from a snapshot of the open sessions, so one taken just
    before a session ends can reach save_detection after handle_remove has
    written the final verdict. The upsert guards on evaluated_at, so the older
    write is dropped rather than resurrecting the stale score.
    """
    repo.save_device(Device(id="dev-1"))
    session = Session.start(device_id="dev-1")
    repo.save_session(session)

    final = Detection(
        session_id=session.id,
        score=80,
        verdict="malicious",
        hits=[],
        evaluated_at=200.0,
    )
    stale = Detection(
        session_id=session.id, score=10, verdict="benign", hits=[], evaluated_at=100.0
    )
    repo.save_detection(final)
    repo.save_detection(stale)  # arrives late, older timestamp

    stored = repo.get_detection(session.id)
    assert stored.score == 80
    assert stored.verdict == "malicious"
