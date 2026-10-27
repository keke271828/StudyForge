"""Internal request identity for the paired mobile gateway, never an HTTP header."""
from contextvars import ContextVar

remote_device: ContextVar[str | None] = ContextVar('studyforge_remote_device', default=None)
