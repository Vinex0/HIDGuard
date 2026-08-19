from itertools import pairwise
from statistics import fmean, median, pstdev

from evdev.ecodes import KEY_BACKSPACE

from hidguard.models.input_event import InputEvent
from hidguard.models.session import Session
from hidguard.storage.sqlite_repo import SqliteRepo


class Features:
    def __init__(self, repo : SqliteRepo):
        self.repo = repo

    def update_session(self, session: Session) -> Session:
        events = self.repo.get_events_for_session(session.id)
        return session.model_copy(update=self.extract_features(events, session.connected_at))

    def extract_features(self, events: list[InputEvent], connected_at: float) -> dict:
        presses = [event for event in events if event.value == 1] #only down presses
        
        #inter key delays in ms
        delays = [(b.timestamp - a.timestamp) * 1000 for a, b in pairwise(presses)]

        features = {
            "event_count" : len(events),
            "backspace_count" : sum(1 for event in presses if event.code==KEY_BACKSPACE),

        }
        if presses:
            features["time_to_first_keystroke_ms"] = (presses[0].timestamp - connected_at) * 1000

        if delays:
            features |= {
            "avg_interkey_delay_ms" : fmean(delays),
            "std_interkey_delay_ms" : pstdev(delays),
            "min_interkey_delay_ms" : min(delays),
            "max_interkey_delay_ms" : max(delays),
            "median_interkey_delay_ms" : median(delays)
            }

        return features