"""Rule-based scoring of one session's keystroke features.

evaluate is a pure function over a Session: everything it reads was computed by
the feature extraction and stored, so the rules can be tested against hand-built
sessions without a database, a device, or a clock.

Every threshold is a constant with the reasoning that produced it directly above
it. That block is the table this module gets cited as -- changing a number is a
change to it, not to the code below.
"""

from collections.abc import Callable
from typing import Literal

from hidguard.models.detection import Detection, RuleHit
from hidguard.models.session import Session

# --- Gates -------------------------------------------------------------------

# Below this, no rule runs. Plugging a keyboard in and hitting a key or two says
# nothing about who is typing, and would score on instant_typing every time.
MIN_KEYSTROKES = 5

# Spread over a handful of samples is dominated by which samples happened to
# land, so the distribution rules wait for more data than the threshold rules do.
MIN_KEYSTROKES_FOR_STATISTICS = 10

# --- Speed -------------------------------------------------------------------

# 40-60 WPM is 200-240ms per keystroke; professional typists at 90-120 WPM reach
# 100-133ms; the recognised sustained record (Blackburn, 212 WPM) is about 56ms.
# 50ms is therefore >240 WPM -- out of reach for anyone but a record holder --
# and 25ms is >480 WPM, which no hand produces.
SUPERHUMAN_DELAY_MS = 25.0
FAST_DELAY_MS = 50.0

# --- Variability -------------------------------------------------------------

# Interkey intervals are lognormally distributed; the difference between a
# same-hand digraph and an alternating-hand one alone accounts for 50-100ms.
# Human CV sits around 0.4-0.9 and does not drop below 0.15 even when someone
# deliberately types metronomically, so CV < 0.10 is a machine, not a person.
RIGID_STD_MS = 5.0
RIGID_CV = 0.10
LOW_JITTER_STD_MS = 15.0
LOW_JITTER_CV = 0.20

# Human hold times run 60-120ms with a std of 20-40ms. An injector emits the
# press and release report back to back, giving a near-constant hold.
UNIFORM_DWELL_STD_MS = 3.0

# --- Bursts ------------------------------------------------------------------

# 20 keystrokes inside one second is 240 WPM sustained for that second.
BURST_RATE_KEYS_PER_S = 20

# 50 consecutive keystrokes with no gap over the burst threshold. Humans break
# up long runs to look at the screen; a payload types its line and moves on.
LONG_BURST_LENGTH = 50

# --- Payload shape -----------------------------------------------------------

# A person has to move their hands to the keyboard after plugging it in, so
# under 500ms is not physically plausible. Ducky scripts wait 500-3000ms for
# driver enumeration and then type immediately.
INSTANT_TYPING_MS = 500.0
FAST_START_MS = 2000.0

# The first move of practically every payload is opening a terminal or a run
# dialog; the window covers the enumeration delay those scripts wait out.
LAUNCHER_WINDOW_MS = 3000.0

# Typing this much without a single correction is unusual for a person and
# expected of a script, but weak on its own -- hence the low score.
CLEAN_RUN_KEYSTROKES = 60

# --- Verdict -----------------------------------------------------------------

# No single rule reaches malicious: instant_typing (40) alone is suspicious, and
# so is superhuman_speed + no_jitter (55). Malicious requires corroboration from
# at least two independent families of evidence -- timing, burst shape, payload.
SUSPICIOUS_SCORE = 30
MALICIOUS_SCORE = 60


def _instant_typing(session: Session) -> RuleHit | None:
    delay = session.time_to_first_keystroke_ms
    if delay is None:
        return None
    reason = f"first keystroke {delay:.0f}ms after enumeration"
    if delay < INSTANT_TYPING_MS:
        return RuleHit(rule="instant_typing", score=40, reason=reason)
    if delay < FAST_START_MS:
        return RuleHit(rule="instant_typing", score=30, reason=reason)
    return None


def _superhuman_speed(session: Session) -> RuleHit | None:
    """Scored on the median, not the mean.

    A single pause for thought drags the mean over the threshold, so an attacker
    would only need one DELAY 2000 in the middle of the payload to hide. The
    median is robust in both directions; avg_interkey_delay_ms survives as a
    feature regardless.
    """
    delay = session.median_interkey_delay_ms
    if delay is None:
        return None
    reason = f"median interkey delay {delay:.0f}ms"
    if delay < SUPERHUMAN_DELAY_MS:
        return RuleHit(rule="superhuman_speed", score=30, reason=reason)
    if delay < FAST_DELAY_MS:
        return RuleHit(rule="superhuman_speed", score=15, reason=reason)
    return None


def _no_jitter(session: Session) -> RuleHit | None:
    """Absolute spread OR relative spread, deliberately as one rule.

    Split in two, the same observation would be paid for twice: 12ms +/- 1ms
    trips both and collects 50 points from a single measurement. Joined by OR
    the score stays honest, and the CV branch still catches what absolute std
    cannot see -- an injector clocked slowly on purpose (150ms +/- 3ms is a CV
    of 0.02, while superhuman_speed does not fire at all).
    """
    std = session.std_interkey_delay_ms
    median = session.median_interkey_delay_ms
    if std is None:
        return None

    cv = std / median if median else None
    reason = f"interkey std {std:.1f}ms" + (f", CV {cv:.2f}" if cv is not None else "")

    if std < RIGID_STD_MS or (cv is not None and cv < RIGID_CV):
        return RuleHit(rule="no_jitter", score=25, reason=reason)
    if std < LOW_JITTER_STD_MS or (cv is not None and cv < LOW_JITTER_CV):
        return RuleHit(rule="no_jitter", score=10, reason=reason)
    return None


def _uniform_dwell(session: Session) -> RuleHit | None:
    std = session.std_dwell_time_ms
    if std is None or std >= UNIFORM_DWELL_STD_MS:
        return None
    return RuleHit(rule="uniform_dwell", score=10, reason=f"dwell std {std:.1f}ms")


def _burst_rate(session: Session) -> RuleHit | None:
    rate = session.max_keys_per_second
    if rate is None or rate <= BURST_RATE_KEYS_PER_S:
        return None
    return RuleHit(rule="burst_rate", score=20, reason=f"{rate} keystrokes in one second")


def _long_burst(session: Session) -> RuleHit | None:
    length = session.longest_burst_length
    if length is None or length < LONG_BURST_LENGTH:
        return None
    return RuleHit(rule="long_burst", score=15, reason=f"{length} keystrokes in one unbroken burst")


def _launcher_sequence(session: Session) -> RuleHit | None:
    delay = session.launcher_hotkey_after_ms
    if delay is None or delay >= LAUNCHER_WINDOW_MS:
        return None
    return RuleHit(
        rule="launcher_sequence",
        score=20,
        reason=f"launcher hotkey {delay:.0f}ms after enumeration",
    )


def _no_corrections(session: Session) -> RuleHit | None:
    if session.keystroke_count < CLEAN_RUN_KEYSTROKES or session.backspace_count:
        return None
    return RuleHit(
        rule="no_corrections",
        score=10,
        reason=f"{session.keystroke_count} keystrokes, no backspace",
    )


# Each rule paired with the keystroke count it needs before it may run, so the
# gate is readable next to the rule rather than buried inside it.
RULES: list[tuple[Callable[[Session], RuleHit | None], int]] = [
    (_instant_typing, MIN_KEYSTROKES),
    (_superhuman_speed, MIN_KEYSTROKES_FOR_STATISTICS),
    (_no_jitter, MIN_KEYSTROKES_FOR_STATISTICS),
    (_uniform_dwell, MIN_KEYSTROKES_FOR_STATISTICS),
    (_burst_rate, MIN_KEYSTROKES),
    (_long_burst, MIN_KEYSTROKES),
    (_launcher_sequence, MIN_KEYSTROKES),
    (_no_corrections, MIN_KEYSTROKES),
]


def evaluate(session: Session) -> Detection:
    """Scores one session against every rule whose gate it clears.

    Rules that find their input missing return None: the feature extraction
    leaves statistics NULL when there was nothing to compute them from, and that
    absence must not be read as a measurement of zero.

    A session too short to say anything is reported as such rather than scored:

    >>> from uuid import UUID
    >>> quiet = Session(
    ...     id=UUID(int=0), device_id="dev-1", connected_at=0.0, keystroke_count=3
    ... )
    >>> evaluate(quiet).verdict
    'insufficient_data'

    An injected payload trips several independent rules at once:

    >>> injected = Session(
    ...     id=UUID(int=0),
    ...     device_id="dev-1",
    ...     connected_at=0.0,
    ...     keystroke_count=80,
    ...     time_to_first_keystroke_ms=200.0,
    ...     median_interkey_delay_ms=12.0,
    ...     std_interkey_delay_ms=0.5,
    ... )
    >>> detection = evaluate(injected)
    >>> [hit.rule for hit in detection.hits]
    ['instant_typing', 'superhuman_speed', 'no_jitter', 'no_corrections']
    >>> detection.verdict
    'malicious'
    """
    if session.keystroke_count < MIN_KEYSTROKES:
        return Detection(session_id=session.id, score=0, verdict="insufficient_data")

    hits = []
    for rule, min_keystrokes in RULES:
        if session.keystroke_count < min_keystrokes:
            continue
        hit = rule(session)
        if hit is not None:
            hits.append(hit)

    score = sum(hit.score for hit in hits)
    return Detection(session_id=session.id, score=score, verdict=_verdict(score), hits=hits)


def _verdict(score: int) -> Literal["benign", "suspicious", "malicious"]:
    """The label for a total score, at the thresholds documented above.

    >>> _verdict(0), _verdict(SUSPICIOUS_SCORE - 1)
    ('benign', 'benign')
    >>> _verdict(SUSPICIOUS_SCORE), _verdict(MALICIOUS_SCORE - 1)
    ('suspicious', 'suspicious')
    >>> _verdict(MALICIOUS_SCORE)
    'malicious'
    """
    if score >= MALICIOUS_SCORE:
        return "malicious"
    if score >= SUSPICIOUS_SCORE:
        return "suspicious"
    return "benign"
