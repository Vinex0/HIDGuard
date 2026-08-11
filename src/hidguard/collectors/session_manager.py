import threading
from uuid import UUID

from hidguard.models.session import Session


class SessionManager:
    """Tracks active device sessions and their reader threads."""

    def __init__(self):
        self._readers: dict[str, tuple[threading.Thread, threading.Event]] = {}
        self._sessions: dict[str, Session] = {}

    def register(self, node: str, session: Session, thread: threading.Thread, stop_event: threading.Event) -> None:
        """Tracks a session and its reader thread against a device node.

        Any registration already held for the node is retired first: device
        nodes get reused after a fast unplug/replug, and overwriting outright
        would strand the old reader with its stop event never set.
        """
        self.unregister(node)
        self._sessions[node] = session
        self._readers[node] = (thread, stop_event)

    def unregister(self, node: str) -> Session | None:
        """Stops the reader thread and ends the session for a device node, if tracked."""
        if node in self._readers:
            _, stop_event = self._readers.pop(node)
            stop_event.set()

        session = self._sessions.pop(node, None)
        if session:
            session.end()
        return session

    def session_id_for(self, node: str) -> UUID | None:
        session = self._sessions.get(node)
        return session.id if session else None