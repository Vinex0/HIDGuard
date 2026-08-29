# HIDGuard

Behavior-based detection of HID-injection attacks (Rubber Ducky and similar).
Instead of trusting a device's declared identity, HIDGuard watches *how* a
keyboard types -- speed, rhythm, dwell times, burst shape -- and flags the
machine-regular cadence a scripted payload produces but a human hand cannot.

The pipeline: a udev listener opens a session per keyboard, an evdev reader
records its events, keystroke features are extracted into SQLite, and a
rule-based engine scores each session. An open session is re-scored every couple
of seconds, so an attack is flagged *while it is happening*, not only when the
device is unplugged.

## Requirements

- Linux with `/dev/uinput` and evdev input devices (a standard desktop)
- [uv](https://docs.astral.sh/uv/) for dependency management and running
- `sudo`, because reading input devices and creating a virtual keyboard both
  require root (see [Why sudo](#why-sudo))

## Install

```bash
uv sync
```

This creates `.venv/` and installs the `hidguard` command into it.

## Run

**One command starts the program with its live dashboard:**

```bash
sudo .venv/bin/hidguard
```

This opens the detection daemon and a live terminal dashboard in the same
window. Plug and unplug a keyboard, or run the simulator below, and watch the
verdict land: `benign`, `suspicious`, or `malicious`, with the signals that
triggered it.

To see a malicious verdict without hardware, run the simulator in a **second
terminal** while the command above is running:

```bash
sudo .venv/bin/hidguard simulate --payload superhuman --countdown 15
```

### Other run modes

```bash
sudo .venv/bin/hidguard --headless    # daemon only, prints status, no dashboard
sudo .venv/bin/hidguard dashboard     # a dashboard attached to a daemon started elsewhere
```

A bare `hidguard` is the same as `hidguard run`.

### The attack simulator

`hidguard simulate` demonstrates detection without any special hardware. It
creates a real virtual keyboard through `/dev/uinput` -- exactly what a Rubber
Ducky does when it enumerates as a HID device -- and types a preset payload into
the **currently focused window**. The effect is deliberately visible and
harmless: focus a scratch text editor during the countdown and watch the text
appear at machine speed. No Enter is ever sent, so nothing executes.

```bash
sudo .venv/bin/hidguard simulate --list   # describe the presets
```

| Preset       | Behavior                                   | Expected verdict |
|--------------|--------------------------------------------|------------------|
| `benign`     | Human-speed typing with natural jitter     | benign           |
| `superhuman` | Fixed 12 ms cadence, no jitter             | malicious        |
| `launcher`   | Opens a terminal, then types fast          | malicious        |

Aim it at a scratch editor or an empty virtual terminal (`Ctrl+Alt+F3`), never
at a shell you care about.

## Why sudo

- **`hidguard` / `hidguard dashboard`** read `/dev/input/eventN` to capture
  keystrokes, which requires root (or membership in the `input` group).
- **`hidguard simulate`** writes to `/dev/uinput`, which is root-only.

Run every command the same way (`sudo .venv/bin/hidguard ...`) so the SQLite
database under `data/` stays owned by one user. If you switch between `sudo` and
non-`sudo` runs you may hit `attempt to write a readonly database`; delete
`data/hidguard.db*` and start fresh.

A non-root deployment (add the user to the `input` group and grant `/dev/uinput`
via a udev rule) is possible but out of scope here.

## Development

```bash
uv run pytest                      # unit tests and doctests (see below)
sudo uv run pytest -m integration  # the /dev/uinput test, deselected by default
uv run ruff check src tests        # linter
uv run ruff format --check src tests
uv run mypy src                    # type checker
uv run interrogate -v src          # docstring coverage
```

`pytest` collects both the unit tests in `tests/` and the doctests in `src/`
(`--doctest-modules` is set in `pyproject.toml`), so a docstring whose example
drifts from the code fails the suite.

The scoring thresholds all live in one annotated block in
[`detection/engine.py`](src/hidguard/detection/engine.py); each constant carries
the reasoning that produced it.

### Errors

Failures the person running HIDGuard can do something about -- a database owned
by another user, a daemon started without the privileges it needs -- are raised
as [`HidGuardError`](src/hidguard/errors.py) subclasses and printed by the CLI
as one line with exit code 1. Anything else keeps its traceback, so a bug still
looks like a bug. Bad flag values never get that far: each flag validates its
own input, and argparse reports them with usage and exit code 2.
