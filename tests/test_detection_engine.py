"""Unit tests for the scoring rules.

evaluate is a pure function over a Session, so every test here builds one by
hand and asserts on the returned Detection -- no repo, no device, no events.
session_with starts from a session that clears both gates and overrides only
the features under test, which keeps each case down to the fields that matter.
"""

from uuid import uuid4

from hidguard.detection import engine
from hidguard.models.detection import RuleHit
from hidguard.models.session import Session


def session_with(**features) -> Session:
    """A session past both keystroke gates, with individual features overridden.

    Everything not named stays at the model default: the optional statistics are
    None and backspace_count is 0, so a rule only fires when a test asked for it.
    """
    defaults = {
        "id": uuid4(),
        "device_id": "fake-device",
        "connected_at": 0.0,
        "keystroke_count": 20,
    }
    return Session(**(defaults | features))


def hit_for(rule: str, session: Session) -> RuleHit | None:
    return next((hit for hit in engine.evaluate(session).hits if hit.rule == rule), None)


def score_of(rule: str, session: Session) -> int:
    hit = hit_for(rule, session)
    return hit.score if hit else 0


def test_instant_typing_scores_both_stages():
    """Under 500ms is the strong stage; under 2000ms the weaker one.

    500ms itself belongs to the weaker stage -- the comparisons are strict, so a
    value landing exactly on a threshold falls through to the tier below.
    """
    assert score_of("instant_typing", session_with(time_to_first_keystroke_ms=100.0)) == 40
    assert score_of("instant_typing", session_with(time_to_first_keystroke_ms=500.0)) == 30
    assert score_of("instant_typing", session_with(time_to_first_keystroke_ms=1500.0)) == 30
    assert score_of("instant_typing", session_with(time_to_first_keystroke_ms=2000.0)) == 0


def test_superhuman_speed_scores_both_stages():
    assert score_of("superhuman_speed", session_with(median_interkey_delay_ms=10.0)) == 30
    assert score_of("superhuman_speed", session_with(median_interkey_delay_ms=25.0)) == 15
    assert score_of("superhuman_speed", session_with(median_interkey_delay_ms=40.0)) == 15
    assert score_of("superhuman_speed", session_with(median_interkey_delay_ms=50.0)) == 0


def test_no_jitter_scores_on_absolute_spread_alone():
    """A session with no median still gets scored on its standard deviation.

    The CV branch needs a median to divide by; when there is none the rule falls
    back to absolute spread rather than declining to fire, and says so in the
    reason it records.
    """
    hit = hit_for("no_jitter", session_with(std_interkey_delay_ms=2.0))

    assert hit is not None
    assert hit.score == 25
    assert "CV" not in hit.reason


def test_no_jitter_scores_its_weaker_stage():
    """12ms +/- 12ms is loose enough for the second tier and no further."""
    session = session_with(std_interkey_delay_ms=12.0, median_interkey_delay_ms=100.0)

    assert score_of("no_jitter", session) == 10


def test_no_jitter_leaves_human_variability_alone():
    """40ms spread around a 200ms median is a CV of 0.20 -- ordinary typing.

    Exactly on the threshold, so this pins that the weaker stage does not reach
    down into the range where real people live.
    """
    session = session_with(std_interkey_delay_ms=40.0, median_interkey_delay_ms=200.0)

    assert score_of("no_jitter", session) == 0


def test_no_jitter_catches_a_deliberately_slow_injector():
    """150ms +/- 10ms is a CV of 0.07: machine-regular, but not fast.

    This is the case the CV branch exists for. Absolute spread of 10ms would
    pass for human, and at 150ms per keystroke superhuman_speed stays silent, so
    without the relative branch a slowed-down injector would score nothing here.
    """
    session = session_with(std_interkey_delay_ms=10.0, median_interkey_delay_ms=150.0)

    assert score_of("no_jitter", session) == 25
    assert score_of("superhuman_speed", session) == 0


def test_uniform_dwell_fires_below_three_milliseconds():
    assert score_of("uniform_dwell", session_with(std_dwell_time_ms=1.0)) == 10
    assert score_of("uniform_dwell", session_with(std_dwell_time_ms=3.0)) == 0


def test_burst_rate_fires_above_twenty_keys_per_second():
    assert score_of("burst_rate", session_with(max_keys_per_second=21)) == 20
    assert score_of("burst_rate", session_with(max_keys_per_second=20)) == 0


def test_long_burst_fires_at_fifty_keystrokes():
    """Inclusive, unlike the other thresholds: the rule is phrased 'at least'."""
    assert score_of("long_burst", session_with(longest_burst_length=50)) == 15
    assert score_of("long_burst", session_with(longest_burst_length=49)) == 0


def test_launcher_sequence_fires_inside_the_window():
    assert score_of("launcher_sequence", session_with(launcher_hotkey_after_ms=1200.0)) == 20
    assert score_of("launcher_sequence", session_with(launcher_hotkey_after_ms=3000.0)) == 0


def test_no_corrections_needs_a_long_clean_run():
    """Sixty keystrokes and no backspace; a single correction is enough to clear it."""
    assert score_of("no_corrections", session_with(keystroke_count=60)) == 10
    assert score_of("no_corrections", session_with(keystroke_count=59)) == 0
    assert score_of("no_corrections", session_with(keystroke_count=60, backspace_count=1)) == 0


def test_too_few_keystrokes_short_circuits_every_rule():
    """Four keystrokes are scored as insufficient_data, not as benign.

    The session would otherwise collect 40 points for instant_typing: touching a
    key right after plugging a keyboard in is what everybody does, and there is
    no evidence yet to weigh it against.
    """
    detection = engine.evaluate(
        session_with(keystroke_count=4, time_to_first_keystroke_ms=100.0)
    )

    assert detection.verdict == "insufficient_data"
    assert detection.score == 0
    assert detection.hits == []


def test_statistics_gate_holds_back_only_the_distribution_rules():
    """At seven keystrokes the spread rules stay quiet while the rest still score.

    A standard deviation over six interkey gaps is mostly an accident of which
    gaps happened to land, so no_jitter waits for ten keystrokes -- but a burst
    of 25 keys in a second is a direct measurement and needs no such patience.
    """
    session = session_with(
        keystroke_count=7, std_interkey_delay_ms=1.0, max_keys_per_second=25
    )

    assert hit_for("no_jitter", session) is None
    assert score_of("burst_rate", session) == 20


def test_missing_features_score_nothing_rather_than_raising():
    """Every optional field None runs through all eight rules and lands on benign.

    This is the session the feature extraction produces when it had too little
    to compute statistics from, and the rules have to read that absence as 'not
    measured' instead of dividing by it or comparing None to a number.
    """
    detection = engine.evaluate(session_with(keystroke_count=20))

    assert detection.verdict == "benign"
    assert detection.score == 0
    assert detection.hits == []


def test_verdict_boundaries():
    """The thresholds are inclusive, checked one point below each.

    Called directly rather than through evaluate: every rule scores in steps of
    five, so no combination of them can produce 29 or 59 to test with.
    """
    assert engine._verdict(29) == "benign"
    assert engine._verdict(30) == "suspicious"
    assert engine._verdict(59) == "suspicious"
    assert engine._verdict(60) == "malicious"


def test_no_single_rule_reaches_malicious():
    """The heaviest rule, and the heaviest pair, both stop at suspicious.

    Malicious is meant to require corroboration across independent families of
    evidence. instant_typing is the largest single hit at 40, and timing alone
    tops out at 55 with superhuman_speed and no_jitter together.
    """
    only_instant = engine.evaluate(session_with(time_to_first_keystroke_ms=100.0))
    only_timing = engine.evaluate(
        session_with(median_interkey_delay_ms=10.0, std_interkey_delay_ms=2.0)
    )

    assert (only_instant.score, only_instant.verdict) == (40, "suspicious")
    assert (only_timing.score, only_timing.verdict) == (55, "suspicious")


def test_corroborated_evidence_reaches_malicious():
    """Timing, spread and burst shape together: 30 + 25 + 20."""
    detection = engine.evaluate(
        session_with(
            median_interkey_delay_ms=12.0,
            std_interkey_delay_ms=1.0,
            max_keys_per_second=40,
        )
    )

    assert detection.score == 75
    assert detection.verdict == "malicious"
    assert {hit.rule for hit in detection.hits} == {
        "superhuman_speed",
        "no_jitter",
        "burst_rate",
    }


def test_a_fast_flawless_typist_lands_on_the_suspicious_boundary():
    """The expected false positive, pinned so it stays a known quantity.

    Someone typing 21 keys in a second across 60 keystrokes without reaching for
    backspace scores burst_rate plus no_corrections, which is exactly 30. Naming
    the worst benign combination is the point: it sits on the boundary and no
    higher, so a benign session cannot drift into malicious on volume alone.
    """
    detection = engine.evaluate(session_with(keystroke_count=60, max_keys_per_second=21))

    assert detection.score == 30
    assert detection.verdict == "suspicious"
