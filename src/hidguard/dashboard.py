"""Live terminal dashboard for the recent sessions and their verdicts.

Runs as its own read-only process, separate from the daemon: point it at the
same database while hidguard.main is running and watch verdicts land. The
sessions table is opened WAL-mode by the daemon, so a second reader here never
blocks its writes.

    uv run python -m hidguard.dashboard

The one design point worth knowing: an open session's row carries no features
yet, because the scorer writes only the detections table while a session is
live (see detection/scorer.py). So the live numbers shown here come from each
session's detection -- its score, verdict, and the reason strings, which already
carry the measured values -- not from the session row, which fills in only when
the device is unplugged.
"""

import argparse
import time
from uuid import UUID

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.text import Text

from hidguard.models.detection import Detection
from hidguard.models.session import Session
from hidguard.storage.paths import get_db_path
from hidguard.storage.sqlite_repo import SqliteRepo

REFRESH_INTERVAL_S = 1.0
DEFAULT_LIMIT = 15

# Verdict -> (label style, whether it should stand out). Ordered worst-first so
# the legend and any future sorting read the same way.
VERDICT_STYLES = {
    "malicious": "bold white on red",
    "suspicious": "bold yellow",
    "benign": "green",
    "insufficient_data": "dim",
}


def _verdict_cell(verdict: str | None) -> Text:
    if verdict is None:
        return Text("—", style="dim")
    return Text(f" {verdict} ", style=VERDICT_STYLES.get(verdict, ""))


def _status_cell(session: Session) -> Text:
    if session.disconnected_at is None:
        return Text("● live", style="bold green")
    seconds = session.disconnected_at - session.connected_at
    return Text(f"ended ({seconds:.0f}s)", style="dim")


def _reasons_cell(detection: Detection | None) -> Text:
    if detection is None or not detection.hits:
        return Text("—", style="dim")
    return Text("\n".join(f"{hit.rule}: {hit.reason}" for hit in detection.hits))


def _device_label(repo: SqliteRepo, device_id: str) -> str:
    device = repo.get_device(device_id)
    if device and (device.vendor_name or device.model_name):
        return " ".join(p for p in (device.vendor_name, device.model_name) if p)
    return device_id


def render(repo: SqliteRepo, limit: int) -> Table:
    """Build the table from the current database state, newest session first."""
    detections: dict[UUID, Detection] = {
        detection.session_id: detection for detection in repo.list_detections()
    }

    table = Table(
        title="HIDGuard — recent sessions",
        caption=f"refreshed {time.strftime('%H:%M:%S')}  ·  Ctrl+C to quit",
        expand=True,
    )
    table.add_column("Session", no_wrap=True)
    table.add_column("Device")
    table.add_column("Status", no_wrap=True)
    table.add_column("Verdict", no_wrap=True)
    table.add_column("Score", justify="right", no_wrap=True)
    table.add_column("Signals", ratio=1)

    for session in repo.list_session(limit=limit):
        detection = detections.get(session.id)
        table.add_row(
            str(session.id)[:8],
            _device_label(repo, session.device_id),
            _status_cell(session),
            _verdict_cell(detection.verdict if detection else None),
            str(detection.score) if detection else "—",
            _reasons_cell(detection),
        )

    return table


def run(db_path, limit: int, interval: float) -> None:
    repo = SqliteRepo(db_path)
    console = Console()
    try:
        with Live(render(repo, limit), console=console, screen=True, auto_refresh=False) as live:
            while True:
                live.update(render(repo, limit), refresh=True)
                time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        repo.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT,
        help=f"how many recent sessions to show (default: {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--interval", type=float, default=REFRESH_INTERVAL_S,
        help=f"seconds between refreshes (default: {REFRESH_INTERVAL_S})",
    )
    args = parser.parse_args()
    run(get_db_path(), args.limit, args.interval)


if __name__ == "__main__":
    main()
