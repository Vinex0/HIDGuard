"""The failures HIDGuard reports to its user rather than as a traceback.

Everything raised here is a condition the person running the program can act
on -- a database owned by another user, a daemon started without the privileges
it needs -- as opposed to a bug, which should still surface with its traceback
intact. The CLI catches this one base class and prints it as a single line, so
each new failure mode needs a subclass and a message, not another except branch.
"""


class HidGuardError(RuntimeError):
    """Base class for every failure HIDGuard reports as a message."""


class StorageError(HidGuardError):
    """The database could not be opened, read, or written."""


class DaemonError(HidGuardError):
    """The daemon could not start listening for device events."""
